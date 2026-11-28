"""Protecciones HTTP: sesión, CSRF, control de acceso y cabeceras de seguridad."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading
import time
from functools import wraps
from urllib.parse import urlsplit

from flask import Response, abort, g, jsonify, redirect, request, session, url_for

from ..core import accounts, ipban, maintenance, mfa, storage, tokens
from ..core.permissions import effective_for_root, is_admin, permissions_for
from ..db.connection import now_iso
from ..db.repositories import audit
from ..db.repositories import sessions as session_repo
from ..db.repositories import users
from ..i18n import LOCALES, _, reset_locale, set_locale
from ..i18n import normalize as normalize_locale
from .context import get_db, login_limiter, settings


def client_ip() -> str:
    return request.remote_addr or "-"


# Por qué se deniega algo, para los programas (extensión de VS Code, scripts, unidad de red): un código fijo en esta
# cabecera de la respuesta de error (401 account_disabled, token_expired, token_invalid, tokens_disabled,
# password_not_allowed, mfa_requires_token, throttled, signed_out; 403 ip_banned, read_only, token_read_only,
# no_permission; 413 too_large; 503 maintenance). La pone set_security_headers.
REASON_HEADER = "X-StorageWeb-Reason"


def deny(status: int, reason: str, description: str | None = None):
    """Corta la petición con ``status`` y el motivo ``reason`` en :data:`REASON_HEADER`."""
    g.deny_reason = reason
    abort(status, description=description)


def missing_reason(root: dict, needed) -> str:
    """Por qué el usuario de la petición no tiene ``needed`` en ``root``: ``token_read_only`` (su rol y la carpeta
    sí, pero el token es de lectura), ``read_only`` (su rol sí, pero la carpeta es de solo lectura para él) o
    ``no_permission`` (su rol no)."""
    needed = set(needed)
    own = permissions_for(g.user, settings())
    in_root = effective_for_root(own, root)
    if needed <= in_root:
        return "token_read_only"
    if needed <= own:
        return "read_only"
    return "no_permission"


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def csrf_ok(sent: str | None) -> bool:
    """Si ``sent`` es el token CSRF de esta sesión (comparado en tiempo constante)."""
    expected = session.get("_csrf")
    return bool(expected and sent) and hmac.compare_digest(str(expected).encode(), sent.encode())


def check_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    if g.get("api_token") is not None or request.blueprint == DAV_BLUEPRINT:
        return  # sin cookies no hay CSRF posible: las credenciales van en la cabecera
    if request.endpoint in CONNECT_ENDPOINTS:
        return  # canje de un código de /connect: no usa la sesión, el secreto es el verifier (PKCE)
    if not csrf_ok(request.headers.get("X-CSRF-Token") or request.form.get("_csrf")):
        if g.get("session_ended"):
            # La página se abrió con una sesión que ya no existe (la cerró un admin, se desactivó la cuenta, caducó):
            # su token CSRF se fue con ella. No es un ataque: a entrar otra vez (o el 401 para el JavaScript)
            return needs_sign_in()
        ipban.offense(get_db(), settings(), client_ip(), "csrf")
        audit_event("csrf_rejected", request.path, request.method)
        abort(400, description=_("Invalid CSRF token. Reload the page and try again."))


def ip_gate() -> None:
    """Primer filtro: una IP bloqueada no llega a nada más."""
    if ipban.banned(get_db(), client_ip()):
        deny(403, "ip_banned", _("Your IP address is blocked. Contact the administrator."))


def clear_session() -> None:
    """Vacía la sesión conservando el idioma y el tema elegidos (para que no cambien al entrar o salir)."""
    keep = {key: session[key] for key in ("locale", "theme") if session.get(key)}
    session.clear()
    session.update(keep)


def start_session(user, provider_sid: str | None = None) -> None:
    """``provider_sid``: la sesión del proveedor SSO (claim ``sid``), para su cierre de sesión de canal frontal."""
    clear_session()
    session.permanent = True
    session["uid"] = user["id"]
    session["src"] = user["source"]
    session["sid"] = _new_session(user["id"], provider_sid)


def _new_session(user_id: int, provider_sid: str | None = None) -> str:
    sid = secrets.token_urlsafe(24)
    session_repo.create(get_db(), sid, user_id, client_ip(), request.headers.get("User-Agent"), provider_sid)
    return sid


def end_session() -> None:
    """Cierra la sesión actual (también en el servidor)."""
    sid = session.get("sid")
    if sid:
        session_repo.delete(get_db(), sid)
    clear_session()


TOUCH_SECONDS = 60
DAV_BLUEPRINT = "dav"
TOKEN_BLUEPRINTS = ("files", "uploads", "health", DAV_BLUEPRINT)
# Canjes de las aplicaciones (sin cookies, no hay CSRF posible): el código del navegador con su verifier
# (/connect/token) y el token de Microsoft de la cuenta de Windows (/connect/desktop)
CONNECT_ENDPOINTS = frozenset({"connect.token", "connect.desktop"})
METRICS_ENDPOINT = "metrics.metrics_page"


def select_locale() -> None:
    """Idioma de la petición: preferencia del usuario > elegido en la sesión > navegador > por defecto."""
    user = g.get("user")
    locale = (normalize_locale(user["locale"]) if user is not None else None) \
        or normalize_locale(session.get("locale")) \
        or request.accept_languages.best_match(LOCALES) \
        or settings()["default_locale"]
    g.locale_token = set_locale(locale)


def reset_request_locale(_exc=None) -> None:
    token = g.pop("locale_token", None)
    if token is not None:
        reset_locale(token)


def load_current_user() -> None:
    g.user = None
    g.api_token = None
    g.session_id = None
    header = request.headers.get("Authorization", "")
    if request.endpoint == METRICS_ENDPOINT:
        return  # /metrics comprueba su propio token (no es un token de API ni hay sesión)
    if request.blueprint == DAV_BLUEPRINT:
        _load_dav_user(header)  # WebDAV: solo credenciales en la cabecera, nunca la cookie del navegador
        return
    if header[:7].lower() == "bearer ":
        _load_token_user(header[7:].strip())
        return
    uid = session.get("uid")
    if uid is None:
        return
    user = users.get_by_id(get_db(), uid)
    if user is None or not user["enabled"]:
        session.clear()
        g.session_ended = True
        return
    sid = session.get("sid")
    row = session_repo.get(get_db(), sid) if sid else None
    if row is None or row["user_id"] != user["id"]:
        clear_session()  # cerrada por un admin, por cambio de contraseña o caducada
        g.session_ended = True
        return
    now = now_iso()
    if row["last_seen"][:16] < now[:16] or row["ip"] != client_ip():  # como mucho una escritura por minuto
        session_repo.touch(get_db(), sid, client_ip())
    g.user = user
    g.session_id = sid


def _load_token_user(plain: str) -> None:
    cfg = settings()
    if not cfg["security"]["api_tokens"]:
        deny(401, "tokens_disabled", _("API tokens are disabled."))
    found, why = tokens.check(get_db(), plain, client_ip(), cfg["security"]["api_token_max_days"])
    if not found:
        # Solo un token inventado o revocado cuenta como intento: uno caducado o de una cuenta desactivada es de un
        # programa legítimo que reintenta solo (bloquearía la IP de la oficina)
        if why == "token_invalid":
            ipban.offense(get_db(), cfg, client_ip(), "bad_token")
        deny(401, why, _("Your account is disabled.") if why == "account_disabled"
             else _("Invalid or expired API token."))
    g.user, g.api_token = found
    if request.blueprint not in TOKEN_BLUEPRINTS:
        abort(403, description=_("API tokens can only be used to list, download and upload files."))


# Contraseñas de cuenta ya comprobadas en WebDAV (los clientes envían las credenciales en cada petición
# y comprobar el hash cada vez es lento): huella de usuario+contraseña → (id, hash guardado, caducidad).
# Si la contraseña cambia, el hash guardado ya no coincide y se vuelve a comprobar.
_DAV_CACHE: dict[str, tuple[int, str | None, float]] = {}
_DAV_CACHE_LOCK = threading.Lock()
DAV_CACHE_SECONDS = 60


def _dav_cache_key(username: str, password: str) -> str:
    return hashlib.sha256(f"{username.lower()}\0{password}".encode()).hexdigest()


def _load_dav_user(header: str) -> None:
    """WebDAV: ``Basic usuario:token`` (o la contraseña de la cuenta si se permite) o ``Bearer token``."""
    cfg = settings()
    if not cfg["security"]["webdav"]:
        abort(404)
    if header[:7].lower() == "bearer ":
        _load_token_user(header[7:].strip())
        return
    if header[:6].lower() != "basic ":
        return  # sin credenciales: la vista responde 401 para que el cliente las pida
    try:
        username, _sep, password = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        abort(400)
    username = username.rpartition("\\")[2].strip()  # Windows puede enviar «EQUIPO\usuario»
    ip, limiter = client_ip(), login_limiter()
    if not username:
        return
    if limiter.is_blocked(ip, username, DAV_BLUEPRINT):
        g.deny_reason = "throttled"
        return
    user, token, reason = None, None, "bad_password"
    if password.startswith(tokens.PREFIX):
        reason = "bad_token"
        if not cfg["security"]["api_tokens"]:
            g.deny_reason = "tokens_disabled"
            return
        found, why = tokens.check(get_db(), password, ip, cfg["security"]["api_token_max_days"])
        if found and found[0]["username"].lower() == username.lower():
            user, token = found
        elif found is None and why in ("token_expired", "account_disabled"):
            # Un token que fue bueno: un programa legítimo que reintenta solo, no un intento de adivinar
            g.deny_reason = why
            audit.log(get_db(), "login_failed", username=username, ip=ip, detail=f"webdav:{why}")
            return
    elif not cfg["security"]["webdav_passwords"]:
        # La contraseña de la cuenta no se admite: no puede acertar, así que no cuenta como intento (si no,
        # una unidad mal configurada, que reintenta sola, bloquearía al usuario o a la IP de la oficina)
        g.deny_reason = "password_not_allowed"
        audit.log(get_db(), "login_failed", username=username, ip=ip, detail="webdav:password_not_allowed")
        return
    else:
        key = _dav_cache_key(username, password)
        with _DAV_CACHE_LOCK:
            cached = _DAV_CACHE.get(key)
        user = users.get_by_id(get_db(), cached[0]) if cached and cached[2] > time.monotonic() else None
        if user is None or not user["enabled"] or user["password_hash"] != cached[1]:
            try:
                user = accounts.authenticate_password(get_db(), cfg, username, password)
            except accounts.AccountError:  # contraseña buena, cuenta desactivada
                g.deny_reason = "account_disabled"
                audit.log(get_db(), "login_failed", username=username, ip=ip, detail="webdav:account_disabled")
                return
            if user is not None:
                with _DAV_CACHE_LOCK:
                    _DAV_CACHE[key] = (user["id"], user["password_hash"], time.monotonic() + DAV_CACHE_SECONDS)
        if user is not None and mfa.needed(get_db(), cfg, user):
            # Con verificación en dos pasos, la contraseña sola no basta en ningún sitio: en la unidad de red, un
            # token. Es su contraseña correcta, así que no cuenta como intento fallido (la unidad reintenta sola).
            g.deny_reason = "mfa_requires_token"
            audit.log(get_db(), "login_failed", username=username, ip=ip, detail="webdav:mfa_requires_token")
            return
    if user is None:
        if reason == "bad_token":
            g.deny_reason = "token_invalid"
        limiter.failure(ip, username, DAV_BLUEPRINT)
        audit.log(get_db(), "login_failed", username=username, ip=ip, detail=f"webdav:{reason}")
        ipban.offense(get_db(), cfg, ip, "login_failed")
        return
    limiter.success(ip, username, DAV_BLUEPRINT)
    g.user, g.api_token = user, token


def needs_sign_in():
    """Sin sesión (nunca la hubo, caducó, la cerró un admin, la cuenta se desactivó): a la página de entrada. Si
    lo pide el JavaScript de una página (JSON o con la cabecera CSRF), un 401 con el aviso y dónde entrar, que
    common.js (SW.fetch) enseña antes de llevar allí: si no, recibiría la página de entrada como respuesta."""
    if wants_json() or request.headers.get("X-CSRF-Token") or request.headers.get("X-Requested-With") == "fetch":
        g.deny_reason = "signed_out"
        return jsonify(error=_("Your session has ended. Sign in again."), login=url_for("auth.login")), 401
    return redirect(url_for("auth.login", next=_back_after_sign_in()))


def _back_after_sign_in() -> str | None:
    """A dónde volver tras entrar: la página pedida; si era un envío (guardar, borrar…), la página desde la que se
    hizo (``Referer``, solo del propio sitio), que es la que se puede volver a abrir."""
    if request.method in ("GET", "HEAD"):
        return request.full_path
    ref = urlsplit(request.referrer or "")
    if ref.netloc and ref.netloc != request.host:
        return None
    path = ref.path + (f"?{ref.query}" if ref.query else "")
    return path if path and safe_next(path) == path else None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return needs_sign_in()
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return needs_sign_in()
        if not is_admin(g.user):
            abort(403, description=_("This section is for administrators only."))
        return view(*args, **kwargs)
    return wrapper


def safe_next(target: str | None) -> str:
    """Evita open-redirects: solo se aceptan rutas relativas del propio sitio."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("files.index")
    return target


# Páginas que el proveedor SSO carga en un marco invisible (cierre de sesión de canal frontal)
FRAMED_BY_PROVIDER = {"auth.sso_frontchannel_logout"}


def maintenance_gate():
    """Mientras se restaura una copia (``maintenance.RESTORING``), el resto de peticiones esperan fuera: 503."""
    if not maintenance.RESTORING.is_set() or request.endpoint == "static":
        return None
    message = _("A backup is being restored. Try again in a moment.")
    g.deny_reason = "maintenance"
    if request.blueprint == DAV_BLUEPRINT or wants_json():
        return Response(f"503 Service Unavailable\n{message}\n", 503, mimetype="text/plain",
                        headers={"Retry-After": "30"})
    from .errors import error_page  # noqa: PLC0415 (errors importa de aquí)
    return Response(error_page(503, _("Under maintenance"), message), 503, headers={"Retry-After": "30"})


def set_security_headers(response):
    if g.get("deny_reason") and response.status_code >= 400:
        response.headers[REASON_HEADER] = g.deny_reason
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.endpoint in FRAMED_BY_PROVIDER:
        response.headers.setdefault("Content-Security-Policy",
                                    "default-src 'none'; frame-ancestors https://login.microsoftonline.com")
        return response
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self' https://login.microsoftonline.com; base-uri 'self'",
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def with_token(detail: str | None) -> str | None:
    """El detalle de la auditoría con el token de la petición al final (``… token=<nombre>``), si se hizo con
    uno: distingue VS Code («Visual Studio Code (equipo)»), un script o la unidad de red de cada equipo."""
    token = g.get("api_token")
    if token is None:
        return detail
    return f"{detail} token={token['name']}" if detail else f"token={token['name']}"


def audit_event(action: str, target: str | None = None, detail: str | None = None, *, username: str | None = None,
                level: str | None = None) -> None:
    """Registra en la auditoría una acción del usuario de la petición (con su IP y, si lo hay, su token). Sin
    sesión (la pantalla de entrada), ``username`` o nadie."""
    user = g.get("user")
    audit.log(get_db(), action, target, username=username or (user["username"] if user is not None else None),
              ip=client_ip(), detail=with_token(detail), level=level)


def audit_path(action: str, root: dict | str, rel: str, detail: str | None = None) -> None:
    """:func:`audit_event` de una operación sobre una ruta: el objetivo es ``<raíz>:/<ruta>`` (``root``: la raíz o
    su nombre)."""
    name = root if isinstance(root, str) else root["name"]
    audit_event(action, f"{name}:/{rel}", detail)


def root_perms(root: dict) -> frozenset[str]:
    """Lo que el usuario de la petición puede hacer en ``root``: lo de sus roles, recortado por la carpeta (solo
    lectura) y, si entró con un token, por su alcance."""
    return tokens.restrict(effective_for_root(permissions_for(g.user, settings()), root), g.get("api_token"))


def wants_json() -> bool:
    """La petición prefiere JSON (el JavaScript de la página, la API) en vez de una página."""
    return request.accept_mimetypes.best == "application/json"


def require_api_tokens() -> None:
    """403 si los tokens de API están desactivados (``security.api_tokens``)."""
    if not settings()["security"]["api_tokens"]:
        abort(403, description=_("API tokens are disabled."))


def user_or_404(user_uid: str):
    """La cuenta por su identificador público (el de las direcciones); 404 si no existe."""
    user = users.get_by_uid(get_db(), user_uid)
    if user is None:
        abort(404)
    return user


def to_login():
    """A la pantalla de entrada con el formulario de usuario y contraseña a la vista (``manual=1``)."""
    return redirect(url_for("auth.login", manual=1))


# --------------------------------------------------------------------------- transferencias en curso

class TransferGuard:
    """Lo que se vuelve a comprobar mientras se envía una descarga larga (``downloads.guarded``, cada
    ``CHECK_SECONDS``): ``check()`` → ``""`` si puede seguir o el motivo para cortarla; ``cut(motivo)`` lo
    apunta en la auditoría."""

    def __init__(self, check, cut):
        self.check, self.cut = check, cut

    def __call__(self) -> str:
        return self.check()


def transfer_guard(items, perm: str = "download") -> TransferGuard:
    """Para las descargas del usuario de la petición (``items`` = ``[(raíz, ruta)]``): se corta si su cuenta se
    desactiva o se borra, si se cierra su sesión, si se revoca o caduca su token, o si pierde el acceso o el
    permiso en la carpeta (también al desactivar el grupo que se lo daba) o la ruta pasa a estar oculta."""
    uid, sid, token = g.user["id"], g.get("session_id"), g.get("api_token")
    names = {root["name"] for root, _rel in items}
    first_root, first_rel = items[0]

    def check() -> str:
        conn, cfg = get_db(), settings()
        user = users.get_by_id(conn, uid)
        if user is None or not user["enabled"]:
            return "account_disabled"
        if sid is not None and session_repo.get(conn, sid) is None:
            return "signed_out"
        if token is not None and not tokens.still_valid(conn, token["id"], cfg["security"]["api_token_max_days"]):
            return "token_invalid"
        roots = {r["name"]: r for r in storage.available_roots(user, cfg)}  # sin conectar a ningún almacenamiento
        for name in names:
            if name not in roots:
                return "no_access"
            if perm not in tokens.restrict(effective_for_root(permissions_for(user, cfg), roots[name]), token):
                return "no_permission"
        if any(storage.is_hidden(cfg, rel) for _root, rel in items):
            return "hidden"
        return ""

    def cut(why: str) -> None:
        audit_path("download_cut", first_root, first_rel, why)

    return TransferGuard(check, cut)


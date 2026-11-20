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

from flask import Response, abort, g, redirect, render_template, request, session, url_for

from ..core import accounts, ipban, maintenance, mfa, tokens
from ..core.permissions import is_admin
from ..db.connection import now_iso
from ..db.repositories import audit
from ..db.repositories import sessions as session_repo
from ..db.repositories import users
from ..i18n import LOCALES, _, reset_locale, set_locale
from ..i18n import normalize as normalize_locale
from .context import get_db, settings, throttle


def client_ip() -> str:
    return request.remote_addr or "-"


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def check_csrf() -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    if g.get("api_token") is not None or request.blueprint == DAV_BLUEPRINT:
        return  # sin cookies no hay CSRF posible: las credenciales van en la cabecera
    if request.endpoint == CONNECT_TOKEN_ENDPOINT:
        return  # canje de un código de /connect: no usa la sesión, el secreto es el verifier (PKCE)
    expected = session.get("_csrf")
    sent = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        ipban.offense(get_db(), settings(), client_ip(), "csrf")
        audit_event("csrf_rejected", request.path, request.method)
        abort(400, description=_("Invalid CSRF token. Reload the page and try again."))


def ip_gate() -> None:
    """Primer filtro: una IP bloqueada no llega a nada más."""
    if ipban.banned(get_db(), client_ip()):
        abort(403, description=_("Your IP address is blocked. Contact the administrator."))


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
CONNECT_TOKEN_ENDPOINT = "connect.token"
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
        return
    sid = session.get("sid")
    row = session_repo.get(get_db(), sid) if sid else None
    if row is None or row["user_id"] != user["id"]:
        clear_session()  # cerrada por un admin, por cambio de contraseña o caducada
        return
    now = now_iso()
    if row["last_seen"][:16] < now[:16] or row["ip"] != client_ip():  # como mucho una escritura por minuto
        session_repo.touch(get_db(), sid, client_ip())
    g.user = user
    g.session_id = sid


def _load_token_user(plain: str) -> None:
    cfg = settings()
    if not cfg["security"]["api_tokens"]:
        abort(401, description=_("API tokens are disabled."))
    found = tokens.authenticate(get_db(), plain, client_ip(), cfg["security"]["api_token_max_days"])
    if not found:
        ipban.offense(get_db(), cfg, client_ip(), "bad_token")
        abort(401, description=_("Invalid or expired API token."))
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
    ip, limiter = client_ip(), throttle()
    limiter.configure(cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60)
    if not username or limiter.is_blocked(ip, username, DAV_BLUEPRINT):
        return
    user, token, reason = None, None, "bad_password"
    if password.startswith(tokens.PREFIX):
        reason = "bad_token"
        found = tokens.authenticate(get_db(), password, ip, cfg["security"]["api_token_max_days"])             if cfg["security"]["api_tokens"] else None
        if found and found[0]["username"].lower() == username.lower():
            user, token = found
    elif not cfg["security"]["webdav_passwords"]:
        # La contraseña de la cuenta no se admite: no puede acertar, así que no cuenta como intento (si no,
        # una unidad mal configurada, que reintenta sola, bloquearía al usuario o a la IP de la oficina)
        audit.log(get_db(), "login_failed", username=username, ip=ip, detail="webdav:password_not_allowed")
        return
    else:
        key = _dav_cache_key(username, password)
        with _DAV_CACHE_LOCK:
            cached = _DAV_CACHE.get(key)
        user = users.get_by_id(get_db(), cached[0]) if cached and cached[2] > time.monotonic() else None
        if user is None or not user["enabled"] or user["password_hash"] != cached[1]:
            user = accounts.authenticate_password(get_db(), cfg, username, password)
            if user is not None:
                with _DAV_CACHE_LOCK:
                    _DAV_CACHE[key] = (user["id"], user["password_hash"], time.monotonic() + DAV_CACHE_SECONDS)
        if user is not None and mfa.needed(get_db(), cfg, user):
            # Con verificación en dos pasos, la contraseña sola no basta en ningún sitio: en la unidad de red, un
            # token. Es su contraseña correcta, así que no cuenta como intento fallido (la unidad reintenta sola).
            audit.log(get_db(), "login_failed", username=username, ip=ip, detail="webdav:mfa_requires_token")
            return
    if user is None:
        limiter.failure(ip, username, DAV_BLUEPRINT)
        audit.log(get_db(), "login_failed", username=username, ip=ip, detail=f"webdav:{reason}")
        ipban.offense(get_db(), cfg, ip, "login_failed")
        return
    limiter.success(ip, username, DAV_BLUEPRINT)
    g.user, g.api_token = user, token


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.full_path))
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
    if request.blueprint == DAV_BLUEPRINT or request.accept_mimetypes.best == "application/json":
        return Response(f"503 Service Unavailable\n{message}\n", 503, mimetype="text/plain",
                        headers={"Retry-After": "30"})
    return Response(render_template("error.html", code=503, name=_("Under maintenance"), description=message), 503,
                    headers={"Retry-After": "30"})


def set_security_headers(response):
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

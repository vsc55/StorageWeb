"""Protecciones HTTP: sesión, CSRF, control de acceso y cabeceras de seguridad."""
from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from ..core import ipban, tokens
from ..core.permissions import is_admin
from ..db.connection import now_iso
from ..db.repositories import sessions as session_repo
from ..db.repositories import users
from ..i18n import LOCALES, _, reset_locale, set_locale
from ..i18n import normalize as normalize_locale
from .context import get_db, settings


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
    if g.get("api_token") is not None:
        return  # sin cookies no hay CSRF posible: el token va en la cabecera
    expected = session.get("_csrf")
    sent = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        ipban.offense(get_db(), settings(), client_ip(), "csrf")
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


def start_session(user) -> None:
    clear_session()
    session.permanent = True
    session["uid"] = user["id"]
    session["src"] = user["source"]
    session["sid"] = _new_session(user["id"])


def _new_session(user_id: int) -> str:
    sid = secrets.token_urlsafe(24)
    session_repo.create(get_db(), sid, user_id, client_ip(), request.headers.get("User-Agent"))
    return sid


def end_session() -> None:
    """Cierra la sesión actual (también en el servidor)."""
    sid = session.get("sid")
    if sid:
        session_repo.delete(get_db(), sid)
    clear_session()


TOUCH_SECONDS = 60
TOKEN_BLUEPRINTS = ("files", "uploads", "health")


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
    if not sid:
        # Sesión iniciada antes de que existiera el registro de sesiones: se registra ahora
        sid = session["sid"] = _new_session(user["id"])
    else:
        row = session_repo.get(get_db(), sid)
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
    found = tokens.authenticate(get_db(), plain, client_ip())
    if not found:
        ipban.offense(get_db(), cfg, client_ip(), "bad_token")
        abort(401, description=_("Invalid or expired API token."))
    g.user, g.api_token = found
    if request.blueprint not in TOKEN_BLUEPRINTS:
        abort(403, description=_("API tokens can only be used to list, download and upload files."))


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


def set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self' https://login.microsoftonline.com; base-uri 'self'",
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response

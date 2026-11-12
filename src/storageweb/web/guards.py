"""Protecciones HTTP: sesión, CSRF, control de acceso y cabeceras de seguridad."""
from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from ..core.permissions import is_admin
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
    expected = session.get("_csrf")
    sent = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(400, description=_("Invalid CSRF token. Reload the page and try again."))


def clear_session() -> None:
    """Vacía la sesión conservando el idioma elegido (para que no cambie al entrar o salir)."""
    locale = session.get("locale")
    session.clear()
    if locale:
        session["locale"] = locale


def start_session(user) -> None:
    clear_session()
    session.permanent = True
    session["uid"] = user["id"]
    session["src"] = user["source"]


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
    uid = session.get("uid")
    if uid is None:
        return
    user = users.get_by_id(get_db(), uid)
    if user is None or not user["enabled"]:
        session.clear()
        return
    g.user = user


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

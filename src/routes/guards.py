"""Protecciones HTTP: sesión, CSRF, control de acceso y cabeceras de seguridad."""
from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from ..core.permissions import is_admin
from ..db import users


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
        abort(400, description="Token CSRF inválido. Recarga la página e inténtalo de nuevo.")


def start_session(user) -> None:
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["src"] = user["source"]


def load_current_user() -> None:
    g.user = None
    uid = session.get("uid")
    if uid is None:
        return
    user = users.get_by_id(uid)
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
            abort(403, description="Esta sección es solo para administradores.")
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

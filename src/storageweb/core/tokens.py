"""Tokens de API personales.

Un token (``sw_…``) actúa como su usuario, con dos alcances: ``read`` (listar y descargar) o
``write`` (además subir, crear carpetas, renombrar y borrar, según los permisos del rol). Nunca da
acceso a la administración ni al perfil. Solo se guarda su SHA-256: se muestra una única vez.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from ..db.repositories import api_tokens as repo
from ..db.repositories import users
from ..i18n import _, _l

PREFIX = "sw_"
SCOPES = ("read", "write")
SCOPE_LABELS = {"read": _l("Read (list and download)"), "write": _l("Read and write")}
EXPIRY_DAYS = (30, 90, 365, 0)
READ_PERMISSIONS = frozenset({"download"})


class TokenError(Exception):
    pass


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def create(conn: Connection, user, *, name: str, scope: str, days: int) -> tuple[str, int]:
    """Crea un token y devuelve (token en claro, id). El token en claro no se vuelve a poder ver."""
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise TokenError(_("Give the token a name (up to 80 characters)."))
    if scope not in SCOPES:
        raise TokenError(_("Invalid scope: %(scope)s", scope=scope))
    if days not in EXPIRY_DAYS:
        raise TokenError(_("Invalid expiry."))
    plain = PREFIX + secrets.token_urlsafe(32)
    expires = None
    if days:
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
    token_id = repo.create(conn, user_id=user["id"], name=name, token_hash=hash_token(plain),
                           prefix=plain[:len(PREFIX) + 6], scope=scope, expires_at=expires)
    return plain, token_id


def original_days(token) -> int:
    """La caducidad con la que se creó (la más cercana de EXPIRY_DAYS); 0 = no caduca."""
    if not token["expires_at"]:
        return 0
    try:
        span = datetime.fromisoformat(token["expires_at"]) - datetime.fromisoformat(token["created_at"])
    except (TypeError, ValueError):
        return 90
    days = span.total_seconds() / 86400
    return min((d for d in EXPIRY_DAYS if d), key=lambda d: abs(d - days))


def rotate(conn: Connection, user, token) -> tuple[str, int]:
    """Cambia el secreto de un token: uno nuevo con el mismo nombre, alcance y caducidad (contada desde hoy), y
    el anterior deja de valer. Solo el dueño (el admin no debe ver el secreto de otro). Devuelve (en claro, id)."""
    if token is None or token["user_id"] != user["id"]:
        raise TokenError(_("Token not found."))
    plain, token_id = create(conn, user, name=token["name"], scope=token["scope"], days=original_days(token))
    repo.delete(conn, token["id"])
    return plain, token_id


def authenticate(conn: Connection, plain: str, ip: str | None = None):
    """Devuelve (usuario, token) o None si el token no existe, caducó o su usuario está desactivado."""
    if not plain or not plain.startswith(PREFIX) or len(plain) > 100:
        return None
    token = repo.get_by_hash(conn, hash_token(plain))
    if token is None:
        return None
    if token["expires_at"] and token["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds"):
        return None
    user = users.get_by_id(conn, token["user_id"])
    if user is None or not user["enabled"]:
        return None
    repo.touch(conn, token["id"], ip)
    return user, token


def restrict(permissions: frozenset[str], token) -> frozenset[str]:
    """Permisos de una petición hecha con token: los del rol, recortados al alcance del token."""
    if token is None or token["scope"] == "write":
        return permissions
    return permissions & READ_PERMISSIONS

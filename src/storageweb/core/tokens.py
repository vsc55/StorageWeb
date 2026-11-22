"""Tokens de API personales.

Un token (``sw_…``) actúa como su usuario, con dos alcances: ``read`` (listar y descargar) o
``write`` (además subir, crear carpetas, renombrar y borrar, según los permisos del rol). Nunca da
acceso a la administración ni al perfil. Solo se guarda su SHA-256: se muestra una única vez.
"""
from __future__ import annotations

import sqlite3
import secrets
from datetime import datetime, timedelta
from sqlite3 import Connection

from ..db import connect
from ..db.repositories import api_tokens as repo
from ..db.repositories import users
from ..i18n import _, _l, ngettext
from .alerts import alert, source
from ..clock import iso_in, now_iso
from ..text import offered_days, sha256_hex

PREFIX = "sw_"
SCOPES = ("read", "write")
SCOPE_LABELS = {"read": _l("Read (list and download)"), "write": _l("Read and write")}
EXPIRY_DAYS = (30, 90, 365, 0)
READ_PERMISSIONS = frozenset({"download"})


class TokenError(Exception):
    pass


hash_token = sha256_hex


# --------------------------------------------------------------------------- política de caducidad

def allowed_days(max_days: int = 0) -> list[int]:
    """Las caducidades que se pueden elegir con la política ``security.api_token_max_days`` (0 = sin límite):
    las de siempre que no la pasan, sin «nunca», y el propio máximo si no está entre ellas."""
    return offered_days(tuple(d for d in EXPIRY_DAYS if d), max_days)


def clamp_days(days: int, max_days: int = 0) -> int:
    """La caducidad recortada a la política: «nunca» o más larga que el máximo pasan a ser el máximo."""
    return max_days if max_days and (not days or days > max_days) else days


def effective_expiry(token, max_days: int = 0) -> str | None:
    """Cuándo deja de valer de verdad: su caducidad o, con política, su creación más ``max_days`` si es antes
    (los tokens creados antes de la política también la cumplen)."""
    expires = token["expires_at"]
    if not max_days:
        return expires
    try:
        limit = (datetime.fromisoformat(token["created_at"]) + timedelta(days=max_days)).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return expires
    return min(expires, limit) if expires else limit


def create(conn: Connection, user, *, name: str, scope: str, days: int, max_days: int = 0) -> tuple[str, int]:
    """Crea un token y devuelve (token en claro, id). El token en claro no se vuelve a poder ver. Con política
    (``max_days``), no se puede crear sin caducidad ni más largo que el máximo."""
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise TokenError(_("Give the token a name (up to 80 characters)."))
    if scope not in SCOPES:
        raise TokenError(_("Invalid scope: %(scope)s", scope=scope))
    if days not in allowed_days(max_days):
        if max_days and (not days or days > max_days):
            raise TokenError(_("Tokens can last at most %(num)s days.", num=max_days))
        raise TokenError(_("Invalid expiry."))
    plain = PREFIX + secrets.token_urlsafe(32)
    expires = None
    if days:
        expires = iso_in(days=days)
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


def rotate(conn: Connection, user, token, max_days: int = 0) -> tuple[str, int]:
    """Cambia el secreto de un token: uno nuevo con el mismo nombre, alcance y caducidad (contada desde hoy, y
    recortada a la política si la hay), y el anterior deja de valer. Solo el dueño (el admin no debe ver el
    secreto de otro). Devuelve (en claro, id)."""
    if token is None or token["user_id"] != user["id"]:
        raise TokenError(_("Token not found."))
    plain, token_id = create(conn, user, name=token["name"], scope=token["scope"],
                             days=clamp_days(original_days(token), max_days), max_days=max_days)
    repo.delete(conn, token["id"])
    return plain, token_id


def check(conn: Connection, plain: str, ip: str | None = None, max_days: int = 0):
    """``((usuario, token), "")`` si vale; si no, ``(None, motivo)``: ``token_invalid`` (no existe: revocado,
    borrado o inventado), ``token_expired`` (caducó por su fecha o por la política ``max_days``) o
    ``account_disabled`` (su cuenta está desactivada). El motivo se le dice al cliente (cabecera
    ``X-StorageWeb-Reason``): los dos últimos solo los ve quien tiene un token que fue bueno."""
    if not plain or not plain.startswith(PREFIX) or len(plain) > 100:
        return None, "token_invalid"
    token = repo.get_by_hash(conn, hash_token(plain))
    if token is None:
        return None, "token_invalid"
    expires = effective_expiry(token, max_days)
    if expires and expires < now_iso():
        return None, "token_expired"
    user = users.get_by_id(conn, token["user_id"])
    if user is None:
        return None, "token_invalid"
    if not user["enabled"]:
        return None, "account_disabled"
    repo.touch(conn, token["id"], ip)
    return (user, token), ""


def authenticate(conn: Connection, plain: str, ip: str | None = None, max_days: int = 0):
    """Devuelve (usuario, token) o None si el token no existe, caducó (por su fecha o por la política
    ``max_days``) o su usuario está desactivado (:func:`check` dice cuál)."""
    return check(conn, plain, ip, max_days)[0]


def still_valid(conn: Connection, token_id: int, max_days: int = 0) -> bool:
    """Si un token ya comprobado sigue valiendo (no se ha revocado ni ha caducado): para cortar una descarga en
    curso hecha con él."""
    token = repo.get(conn, token_id)
    if token is None:
        return False
    expires = effective_expiry(token, max_days)
    return not (expires and expires < now_iso())


def restrict(permissions: frozenset[str], token) -> frozenset[str]:
    """Permisos de una petición hecha con token: los del rol, recortados al alcance del token."""
    if token is None or token["scope"] == "write":
        return permissions
    return permissions & READ_PERMISSIONS


@source("tokens", order=60)
def _unused_tokens(ctx):
    """Tokens que siguen valiendo pero nadie usa desde hace meses: candidatos a revocar."""
    security = ctx.cfg.get("security") or {}
    days = int(security.get("api_token_unused_days", 90) or 0)      # 0 = sin aviso
    if not security.get("api_tokens") or not days or not ctx.cfg.get("database"):
        return []
    try:
        conn = connect(ctx.cfg["database"])
        try:
            count = repo.unused_for(conn, days)
        finally:
            conn.close()
    except sqlite3.Error:
        return []      # sin base de datos todavía: no hay nada que avisar
    if not count:
        return []
    return [alert("info", "tokens_unused",
                  ngettext("%(num)s API token unused for more than %(days)s days",
                           "%(num)s API tokens unused for more than %(days)s days", count, days=days),
                  _("Tokens nobody uses are better revoked: if one leaks, it still works."),
                  "sessions", _("See the tokens"))]

"""Lectura del directorio de Entra ID: nombre y descripción de los grupos, estado y grupos de las cuentas.

Usa un token de aplicación (``client_credentials`` con el Client ID y el secreto configurados), que
necesita los permisos de aplicación ``Group.Read.All`` (grupos) y ``User.Read.All`` (estado y grupos de
cada cuenta) con consentimiento de administrador. El registro automático los concede; para una aplicación
existente, «Reparar permisos».

Tokens y datos de los grupos se cachean en memoria (50 min y 1 h): estas lecturas solo sirven para mostrar
nombres legibles y rellenar el alta de un grupo, así que un fallo nunca rompe la página (devuelven vacío).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import urllib.parse

from . import oauth2
from .common import endpoints
from .register import GRAPH, RegisterError, _message, _request

TOKEN_TTL = 50 * 60
NAME_TTL = 60 * 60
_log = logging.getLogger(__name__)
_lock = threading.Lock()
_tokens: dict[str, tuple[float, str]] = {}
_info: dict[str, tuple[float, dict | None]] = {}   # object id → (caduca, {"name", "description"} o None)
SELECT = "id,displayName,description"


def _details(obj: dict) -> dict:
    return {"name": obj.get("displayName") or obj["id"], "description": (obj.get("description") or "").strip()}


def configured(ecfg: dict) -> bool:
    """Si hay datos para pedir un token de aplicación a Microsoft."""
    custom = any(ecfg.get(k) for k in ("authorize_url", "token_url", "issuer"))
    return bool(ecfg.get("tenant_id") and ecfg.get("client_id") and ecfg.get("client_secret")) and not custom


def _app_token(ecfg: dict) -> str:
    key = hashlib.sha256(f"{ecfg['tenant_id']}|{ecfg['client_id']}|{ecfg['client_secret']}".encode()).hexdigest()
    with _lock:
        cached = _tokens.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    body = oauth2._http_post(endpoints(ecfg)["token"], {
        "grant_type": "client_credentials", "client_id": ecfg["client_id"],
        "client_secret": ecfg["client_secret"], "scope": "https://graph.microsoft.com/.default"},
        float(ecfg.get("timeout_seconds") or 10))
    token = body.get("access_token")
    if not token:
        raise RegisterError(_message(body) or "no token")
    with _lock:
        _tokens[key] = (time.monotonic() + TOKEN_TTL, token)
    return token


def can_read_groups(access_token: str) -> tuple[bool, str]:
    """(True, "") si el token puede listar grupos; si no, (False, motivo)."""
    try:
        status, data = _request("GET", f"{GRAPH}/groups?$top=1&$select=id", token=access_token)
    except RegisterError as exc:
        return False, str(exc)
    return (True, "") if status == 200 else (False, _message(data) or f"HTTP {status}")


def search_groups(ecfg: dict, text: str, limit: int = 20) -> list[dict]:
    """Grupos cuyo nombre empieza por ``text``: ``[{id, name, description}]``. Vacío si no se puede leer el
    directorio."""
    text = (text or "").strip()
    if len(text) < 2 or not configured(ecfg):
        return []
    query = urllib.parse.quote(text.replace("'", "''"))
    try:
        status, data = _request("GET", f"{GRAPH}/groups?$filter=startswith(displayName,'{query}')"
                                       f"&$select={SELECT}&$top={limit}", token=_app_token(ecfg))
    except RegisterError as exc:
        _log.info("Entra group search failed: %s", exc)
        return []
    if status != 200:
        return []
    groups = [{"id": g["id"].lower(), **_details(g)} for g in data.get("value", [])]
    with _lock:
        for g in groups:
            _info[g["id"]] = (time.monotonic() + NAME_TTL, {"name": g["name"], "description": g["description"]})
    return sorted(groups, key=lambda g: g["name"].lower())


def names_for(ecfg: dict, ids) -> dict[str, str]:
    """``{object_id: nombre}`` de los ids que son grupos. Los que no se puedan resolver no aparecen."""
    return {oid: info["name"] for oid, info in info_for(ecfg, ids).items()}


def info_for(ecfg: dict, ids) -> dict[str, dict]:
    """``{object_id: {"name", "description"}}`` de los ids que son grupos (``getByIds`` devuelve el objeto
    entero). Los que no se puedan resolver no aparecen."""
    wanted = {str(i).lower() for i in ids if i and _looks_like_guid(str(i))}
    if not wanted or not configured(ecfg):
        return {}
    result, missing = {}, []
    now = time.monotonic()
    with _lock:
        for oid in wanted:
            cached = _info.get(oid)
            if cached and cached[0] > now:
                if cached[1]:
                    result[oid] = cached[1]
            else:
                missing.append(oid)
    for start in range(0, len(missing), 1000):
        chunk = missing[start:start + 1000]
        try:
            status, data = _request("POST", f"{GRAPH}/directoryObjects/getByIds", token=_app_token(ecfg),
                                    body={"ids": chunk, "types": ["group"]})
        except RegisterError as exc:
            _log.info("Entra group names failed: %s", exc)
            return result
        if status != 200:
            return result
        found = {o["id"].lower(): _details(o) for o in data.get("value", [])}
        with _lock:
            for oid in chunk:
                _info[oid] = (now + NAME_TTL, found.get(oid))
        result.update(found)
    return result


# --------------------------------------------------------------------------- usuarios (User.Read.All)

def member_groups(ecfg: dict, oid: str) -> list[str] | None:
    """Object IDs de los grupos de seguridad del usuario, también los heredados (``getMemberGroups``), como el
    claim ``groups`` del token. ``None`` si no se pueden leer (sin permiso, sin red…)."""
    if not configured(ecfg) or not oid:
        return None
    try:
        status, data = _request("POST", f"{GRAPH}/users/{urllib.parse.quote(oid, safe='')}/getMemberGroups",
                                token=_app_token(ecfg), body={"securityEnabledOnly": True})
    except RegisterError as exc:
        _log.warning("Entra groups of %s could not be read: %s", oid, exc)
        return None
    if status != 200:
        _log.warning("Entra groups of %s could not be read: %s", oid, _message(data) or status)
        return None
    return sorted({str(g).lower() for g in data.get("value", [])})


def user_state(ecfg: dict, oid: str) -> dict | None:
    """``{"exists": False}`` si la cuenta ya no está en el directorio, ``{"exists": True, "enabled": bool,
    "groups": [...] | None}`` si está; ``None`` si no se puede saber (no se toca nada)."""
    if not configured(ecfg) or not oid:
        return None
    try:
        status, data = _request("GET", f"{GRAPH}/users/{urllib.parse.quote(oid, safe='')}?$select=id,accountEnabled",
                                token=_app_token(ecfg))
    except RegisterError as exc:
        _log.warning("Entra user %s could not be checked: %s", oid, exc)
        return None
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    if status == 404 and error.get("code") == "Request_ResourceNotFound":
        return {"exists": False}
    if status != 200 or "accountEnabled" not in data:
        _log.warning("Entra user %s could not be checked: %s", oid, _message(data) or status)
        return None
    enabled = bool(data["accountEnabled"])
    return {"exists": True, "enabled": enabled, "groups": member_groups(ecfg, oid) if enabled else None}


def can_read_users(access_token: str) -> tuple[bool, str]:
    """(True, "") si el token puede leer el estado de las cuentas; si no, (False, motivo)."""
    try:
        status, data = _request("GET", f"{GRAPH}/users?$top=1&$select=id,accountEnabled", token=access_token)
    except RegisterError as exc:
        return False, str(exc)
    return (True, "") if status == 200 else (False, _message(data) or f"HTTP {status}")


def _looks_like_guid(value: str) -> bool:
    parts = value.split("-")
    return len(value) == 36 and [len(p) for p in parts] == [8, 4, 4, 4, 12]


def clear_cache() -> None:
    with _lock:
        _tokens.clear()
        _info.clear()

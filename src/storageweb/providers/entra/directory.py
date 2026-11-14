"""Lectura del directorio de Entra ID: nombres de los grupos.

Usa un token de aplicación (``client_credentials`` con el Client ID y el secreto configurados), que
necesita el permiso de aplicación ``Group.Read.All`` con consentimiento de administrador. El registro
automático lo concede; para una aplicación existente está el botón «Conceder lectura de grupos».

Tokens y nombres se cachean en memoria (50 min y 1 h): estas lecturas solo sirven para mostrar
nombres legibles, así que un fallo nunca rompe la página (devuelven vacío).
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
_names: dict[str, tuple[float, str | None]] = {}


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
    """Grupos cuyo nombre empieza por ``text``: ``[{id, name}]``. Vacío si no se puede leer el directorio."""
    text = (text or "").strip()
    if len(text) < 2 or not configured(ecfg):
        return []
    query = urllib.parse.quote(text.replace("'", "''"))
    try:
        status, data = _request("GET", f"{GRAPH}/groups?$filter=startswith(displayName,'{query}')"
                                       f"&$select=id,displayName&$top={limit}", token=_app_token(ecfg))
    except RegisterError as exc:
        _log.info("Entra group search failed: %s", exc)
        return []
    if status != 200:
        return []
    groups = [{"id": g["id"].lower(), "name": g.get("displayName") or g["id"]} for g in data.get("value", [])]
    with _lock:
        for g in groups:
            _names[g["id"]] = (time.monotonic() + NAME_TTL, g["name"])
    return sorted(groups, key=lambda g: g["name"].lower())


def names_for(ecfg: dict, ids) -> dict[str, str]:
    """``{object_id: nombre}`` de los ids que son grupos. Los que no se puedan resolver no aparecen."""
    wanted = {str(i).lower() for i in ids if i and _looks_like_guid(str(i))}
    if not wanted or not configured(ecfg):
        return {}
    result, missing = {}, []
    now = time.monotonic()
    with _lock:
        for oid in wanted:
            cached = _names.get(oid)
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
        found = {o["id"].lower(): o.get("displayName") for o in data.get("value", [])}
        with _lock:
            for oid in chunk:
                _names[oid] = (now + NAME_TTL, found.get(oid))
        result.update({k: v for k, v in found.items() if v})
    return result


def _looks_like_guid(value: str) -> bool:
    parts = value.split("-")
    return len(value) == 36 and [len(p) for p in parts] == [8, 4, 4, 4, 12]


def clear_cache() -> None:
    with _lock:
        _tokens.clear()
        _names.clear()

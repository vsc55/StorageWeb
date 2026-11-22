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
import re
import threading
import time
import urllib.parse

from ..base import SSOError
from .common import app_token_request, custom_endpoints
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
    return (bool(ecfg.get("tenant_id") and ecfg.get("client_id") and ecfg.get("client_secret"))
            and not custom_endpoints(ecfg))


def _app_token(ecfg: dict) -> str:
    key = hashlib.sha256(f"{ecfg['tenant_id']}|{ecfg['client_id']}|{ecfg['client_secret']}".encode()).hexdigest()
    with _lock:
        cached = _tokens.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    try:
        body = app_token_request(ecfg, float(ecfg.get("timeout_seconds") or 10))
    except SSOError as exc:
        # Sin red, DNS o Microsoft caído: como cualquier otro fallo de Graph (las páginas no deben romperse)
        raise RegisterError(str(exc)) from exc
    token = body.get("access_token")
    if not token:
        raise RegisterError(_message(body) or "no token")
    with _lock:
        _tokens[key] = (time.monotonic() + TOKEN_TTL, token)
    return token


def _graph(ecfg: dict, method: str, url: str, what: str, *, body: dict | None = None, warn: bool = False):
    """Una llamada a Graph con el token de la aplicación: su JSON si va bien (200); si no (sin permiso, sin red,
    Microsoft caído…), ``None`` y queda en el log con ``what``. Las páginas no se rompen por el directorio."""
    log = _log.warning if warn else _log.info
    try:
        status, data = _request(method, url, token=_app_token(ecfg), body=body)
    except RegisterError as exc:
        log("%s: %s", what, exc)
        return None
    if status != 200:
        log("%s: %s", what, _message(data) or status)
        return None
    return data


def _can_read(access_token: str, url: str) -> tuple[bool, str]:
    """(True, "") si el token puede hacer esa consulta; si no, (False, motivo)."""
    try:
        status, data = _request("GET", url, token=access_token)
    except RegisterError as exc:
        return False, str(exc)
    return (True, "") if status == 200 else (False, _message(data) or f"HTTP {status}")


def can_read_groups(access_token: str) -> tuple[bool, str]:
    """(True, "") si el token puede listar grupos; si no, (False, motivo)."""
    return _can_read(access_token, f"{GRAPH}/groups?$top=1&$select=id")


def _remember_groups(found: list[dict]) -> list[dict]:
    """``[{id, name, description}]`` de los grupos de Graph, guardando su nombre (así no se vuelven a pedir)."""
    groups = [{"id": g["id"].lower(), **_details(g)} for g in found]
    with _lock:
        for g in groups:
            _info[g["id"]] = (time.monotonic() + NAME_TTL, {"name": g["name"], "description": g["description"]})
    return groups


def search_groups(ecfg: dict, text: str, limit: int = 20) -> list[dict] | None:
    """Grupos cuyo nombre empieza por ``text``: ``[{id, name, description}]``. ``None`` si no se puede leer el
    directorio (sin configurar, sin permiso, sin red…); ``[]`` si no hay ninguno o el texto es corto."""
    text = (text or "").strip()
    if not configured(ecfg):
        return None
    if len(text) < 2:
        return []
    query = urllib.parse.quote(text.replace("'", "''"))
    data = _graph(ecfg, "GET", f"{GRAPH}/groups?$filter=startswith(displayName,'{query}')"
                                 f"&$select={SELECT}&$top={int(limit)}", "Entra group search failed")
    if data is None:
        return None
    return sorted(_remember_groups(data.get("value", [])), key=lambda g: g["name"].lower())


def list_groups(ecfg: dict, skiptoken: str = "", page_size: int = 50) -> tuple[list[dict], str] | None:
    """Una página de todos los grupos, por nombre: ``([{id, name, description}], marcador de la siguiente o "")``.
    ``None`` si no se puede leer el directorio (ver :func:`_page`)."""
    page = _page(ecfg, f"{GRAPH}/groups?$select={SELECT}", skiptoken, page_size, "Entra group list failed")
    if page is None:
        return None
    found, following = page
    return _remember_groups(found), following


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
        data = _graph(ecfg, "POST", f"{GRAPH}/directoryObjects/getByIds", "Entra group names failed",
                      body={"ids": chunk, "types": ["group"]})
        if data is None:
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
    data = _graph(ecfg, "POST", f"{GRAPH}/users/{urllib.parse.quote(oid, safe='')}/getMemberGroups",
                  f"Entra groups of {oid} could not be read", body={"securityEnabledOnly": True}, warn=True)
    if data is None:
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


USER_SELECT = "id,displayName,userPrincipalName,mail,accountEnabled,jobTitle,department"


def search_users(ecfg: dict, text: str, limit: int = 25) -> list[dict] | None:
    """Cuentas cuyo nombre, UPN o correo empieza por ``text`` (``User.Read.All``). ``None`` si no se puede leer el
    directorio (sin permiso, sin red…); ``[]`` si no hay ninguna."""
    text = (text or "").strip()
    if not configured(ecfg):
        return None
    if len(text) < 2:
        return []
    value = urllib.parse.quote(text.replace("'", "''"))
    query = (f"startswith(displayName,'{value}') or startswith(userPrincipalName,'{value}') "
             f"or startswith(mail,'{value}')")
    data = _graph(ecfg, "GET", f"{GRAPH}/users?$filter={query}&$select={USER_SELECT}&$top={int(limit)}",
                  "Entra user search failed")
    if data is None:
        return None
    return sorted(data.get("value", []), key=lambda u: str(u.get("displayName") or "").lower())


_SKIPTOKEN_RE = re.compile(r"^[A-Za-z0-9_\-.~!*'()%+=/]{1,4096}$")


def _page(ecfg: dict, url: str, skiptoken: str, page_size: int, what: str) -> tuple[list[dict], str] | None:
    """Una página de una lista de Graph (``url`` con su ``$select``), por nombre: ``(objetos, marcador de la
    siguiente o "")``. ``None`` si no se puede leer el directorio. El marcador es el ``$skiptoken`` de Graph y NADA
    más: la dirección de la página siguiente la compone esto, nunca la que llegue de fuera (con ella el servidor
    mandaría su token a cualquier sitio)."""
    if not configured(ecfg):
        return None
    if skiptoken and not _SKIPTOKEN_RE.match(skiptoken):
        return None
    url += f"&$top={max(1, min(int(page_size), 999))}&$orderby=displayName"
    if skiptoken:
        url += "&$skiptoken=" + urllib.parse.quote(skiptoken, safe="")
    data = _graph(ecfg, "GET", url, what)
    if data is None:
        return None
    following = ""
    link = str(data.get("@odata.nextLink") or "")
    if link:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)
        following = (query.get("$skiptoken") or [""])[0]
    return data.get("value", []), following


def list_users(ecfg: dict, skiptoken: str = "", page_size: int = 50) -> tuple[list[dict], str] | None:
    """Una página de todas las cuentas, por nombre: ``(cuentas, marcador de la siguiente o "")`` (:func:`_page`)."""
    return _page(ecfg, f"{GRAPH}/users?$select={USER_SELECT}", skiptoken, page_size, "Entra user list failed")


def get_user(ecfg: dict, oid: str) -> dict | None:
    """Una cuenta por su Object ID, o ``None`` (no existe o no se puede leer)."""
    if not configured(ecfg) or not _looks_like_guid(str(oid or "")):
        return None
    data = _graph(ecfg, "GET", f"{GRAPH}/users/{urllib.parse.quote(oid, safe='')}?$select={USER_SELECT}",
                  f"Entra user {oid} could not be read")
    return data if data is not None and data.get("id") else None


ASSIGNMENT_TTL = 60          # si la aplicación exige asignación y a quién: se lee una vez por minuto como mucho
_assignments: dict[str, tuple[float, dict | None]] = {}


def assignment(ecfg: dict) -> dict | None:
    """Si la aplicación empresarial exige asignación («Asignación requerida», ``appRoleAssignmentRequired``) y quién
    puede entrar por ella: ``{"required": bool, "users": {oid}}`` con las cuentas asignadas directamente y los
    miembros DIRECTOS de los grupos asignados (Entra ID no aplica la asignación a los grupos anidados). ``None`` si no
    se puede leer (falta ``Application.Read.All``, sin red…): entonces no se sabe, y no se avisa de nada."""
    if not configured(ecfg):
        return None
    key = f"{ecfg['tenant_id']}|{ecfg['client_id']}"
    with _lock:
        cached = _assignments.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    info = _read_assignment(ecfg)
    with _lock:
        _assignments[key] = (time.monotonic() + ASSIGNMENT_TTL, info)
    return info


def _read_assignment(ecfg: dict) -> dict | None:
    client = urllib.parse.quote(str(ecfg["client_id"]).replace("'", "''"))
    try:
        token = _app_token(ecfg)
        status, data = _request("GET", f"{GRAPH}/servicePrincipals?$filter=appId eq '{client}'"
                                       f"&$select=id,appRoleAssignmentRequired", token=token)
        if status != 200 or not data.get("value"):
            _log.info("Entra application could not be read: %s", _message(data) or status)
            return None
        sp = data["value"][0]
        if not sp.get("appRoleAssignmentRequired"):
            return {"required": False, "users": set()}
        users_, groups_ = set(), set()
        assigned_to = _all_pages(f"{GRAPH}/servicePrincipals/{sp['id']}/appRoleAssignedTo"
                                 f"?$select=principalId,principalType&$top=999", token)
        if assigned_to is None:
            return None
        for item in assigned_to:
            (groups_ if item.get("principalType") == "Group" else users_).add(str(item.get("principalId") or "").lower())
        for group in sorted(groups_):
            members = _all_pages(f"{GRAPH}/groups/{urllib.parse.quote(group, safe='')}/members?$select=id&$top=999",
                                 token)
            if members is None:
                return None
            users_.update(str(m.get("id") or "").lower() for m in members)
        return {"required": True, "users": users_}
    except RegisterError as exc:
        _log.info("Entra application could not be read: %s", exc)
        return None


def _all_pages(url: str, token: str, pages: int = 20) -> list[dict] | None:
    """Los ``value`` de una consulta de Graph siguiendo ``@odata.nextLink`` (``pages`` como mucho); ``None`` si falla."""
    out: list[dict] = []
    for _page in range(pages):
        status, data = _request("GET", url, token=token)
        if status != 200:
            _log.info("Entra directory could not be read: %s", _message(data) or status)
            return None
        out.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        if not url:
            break
    return out


def assigned(oid: str, info: dict) -> bool:
    """Si la cuenta puede entrar según la asignación (``info`` de :func:`assignment`)."""
    return not info["required"] or str(oid).lower() in info["users"]


def can_read_users(access_token: str) -> tuple[bool, str]:
    """(True, "") si el token puede leer el estado de las cuentas; si no, (False, motivo)."""
    return _can_read(access_token, f"{GRAPH}/users?$top=1&$select=id,accountEnabled")


def _looks_like_guid(value: str) -> bool:
    parts = value.split("-")
    return len(value) == 36 and [len(p) for p in parts] == [8, 4, 4, 4, 12]


def clear_cache() -> None:
    with _lock:
        _assignments.clear()
        _tokens.clear()
        _info.clear()

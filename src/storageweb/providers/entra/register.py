"""Registro automático de StorageWeb como aplicación de Entra ID.

El administrador inicia sesión con el **flujo de código de dispositivo** (abre
``microsoft.com/devicelogin`` en cualquier navegador y escribe un código) contra un cliente público
de Microsoft. Con ese token delegado se llama a Microsoft Graph para:

1. crear la aplicación (``/applications``): Redirect URI, URL de cierre de sesión de canal frontal, permisos
   ``openid profile email User.Read`` (y, si se pide, ``Group.Read.All`` y ``User.Read.All`` de aplicación),
   claims opcionales ``email`` y ``sid``, App Roles ``StorageWeb.Admin`` y ``StorageWeb.User`` y, si se pide,
   el claim de grupos;
2. crearle un secreto (``addPassword``);
3. crear su *service principal* y, si se pide, exigir asignación;
4. dar el consentimiento de administrador a los permisos (``oauth2PermissionGrants``);
5. asignar al administrador que la registra el rol ``StorageWeb.Admin``.

Los pasos 4 y 5 son de mejor esfuerzo: si fallan, la aplicación ya es usable y se devuelve un aviso
con el enlace al portal. Solo usa la biblioteca estándar.

Inspirado en el asistente «Register in Azure» de ServiceSentry.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from ...i18n import _
from .common import MS_LOGIN
from . import oauth2
from ..base import SSOError

# Microsoft Graph Command Line Tools (el cliente de Connect-MgGraph): cliente público de
# Microsoft que admite el flujo de código de dispositivo y cualquier permiso delegado de Graph.
DEVICE_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
DEVICE_AUTHORITY = f"{MS_LOGIN}/organizations/oauth2/v2.0"
REGISTER_SCOPES = ("https://graph.microsoft.com/Application.ReadWrite.All "
                   "https://graph.microsoft.com/DelegatedPermissionGrant.ReadWrite.All "
                   "https://graph.microsoft.com/AppRoleAssignment.ReadWrite.All")
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
# Permisos delegados de Graph (ids fijos, iguales en todos los tenants)
SIGN_IN_SCOPES = {
    "openid": "37f7f235-527c-4136-accd-4a02d197296e",
    "profile": "14dad69e-099b-42c9-810b-d002981feec1",
    "email": "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0",
    "User.Read": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
}
ADMIN_ROLE, USER_ROLE = "StorageWeb.Admin", "StorageWeb.User"
# Permisos de aplicación de Graph (ids fijos en todos los tenants): nombres de los grupos, estado y grupos de cada
# cuenta (revisión periódica, usuarios con más de 200 grupos, importar personas) y leer la propia aplicación (si
# exige asignación y a quién está asignada: el aviso de Personas → Importar). Solo lectura
GROUP_READ_ALL = "5b567255-7703-4780-807c-7be8301ae99b"
USER_READ_ALL = "df021288-bdef-4463-88db-98f22de89214"
APPLICATION_READ_ALL = "9a5d68dd-52b0-4cc2-bd40-abcf44ac3a30"
DIRECTORY_ROLES = {"Group.Read.All": GROUP_READ_ALL, "User.Read.All": USER_READ_ALL,
                   "Application.Read.All": APPLICATION_READ_ALL}
# Claims opcionales del id_token: el email de las cuentas de la organización (sin él solo llega el de los
# invitados) y la sesión (sid), para el cierre de sesión de canal frontal
ID_TOKEN_CLAIMS = ("email", "sid")


def _optional_claims(current: dict | None, groups: bool = False) -> dict | None:
    """``optionalClaims`` con los que necesita StorageWeb añadidos a los que ya hubiera; ``None`` si no falta
    ninguno."""
    claims = {k: list(v or []) for k, v in (current or {}).items() if k in ("idToken", "accessToken", "saml2Token")}
    id_token = claims.setdefault("idToken", [])
    have = {c.get("name") for c in id_token}
    wanted = [*ID_TOKEN_CLAIMS, *(["groups"] if groups else [])]
    missing = [name for name in wanted if name not in have]
    if not missing:
        return None
    id_token += [{"name": name, "essential": False} for name in missing]
    return claims
SECRET_MONTHS = 24       # sin auth.entra.secret_months (el de serie)
TIMEOUT = 20


def portal_url(client_id: str) -> str:
    """La aplicación en el Centro de administración de Entra (Registros de aplicaciones → la aplicación)."""
    return ("https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade"
            f"/~/Overview/appId/{urllib.parse.quote(client_id, safe='')}")


class RegisterError(Exception):
    pass


# --------------------------------------------------------------------------- HTTP

def _request(method: str, url: str, *, token: str | None = None, form: dict | None = None,
             body: dict | None = None) -> tuple[int, dict]:
    """Petición HTTP que devuelve (estado, JSON). Los errores HTTP no lanzan: devuelven su cuerpo.

    La URL se codifica aquí: las consultas de Graph llevan espacios y comillas (``$filter=appId eq '…'``), y
    Python 3.14 rechaza las URLs con espacios. Lo ya codificado (``%xx``) y los separadores se respetan."""
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%")
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        data = urllib.parse.urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 (URLs fijas de Microsoft)
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, {"error": {"message": raw[:300].decode("utf-8", "replace")}}
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise RegisterError(_("Could not contact Microsoft: %(error)s", error=exc)) from exc


def _message(data: dict) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "")
    return str(data.get("error_description") or err or "")


def _graph(method: str, path: str, token: str, body: dict | None = None, ok=(200, 201, 204)) -> dict:
    status, data = _request(method, f"{GRAPH}{path}", token=token, body=body)
    if status not in ok:
        raise RegisterError(_message(data) or f"HTTP {status}")
    return data


def _claims(access_token: str) -> dict:
    """Claims del token (sin verificar firma: solo se usan tid y oid para llamar a Graph)."""
    try:
        return oauth2.decode_jwt_claims(access_token)
    except SSOError:
        return {}


# --------------------------------------------------------------------------- código de dispositivo

def device_start() -> dict:
    """Pide un código. Devuelve user_code, verification_uri, device_code, expires_in, interval."""
    status, data = _request("POST", f"{DEVICE_AUTHORITY}/devicecode",
                            form={"client_id": DEVICE_CLIENT_ID, "scope": REGISTER_SCOPES})
    if status != 200 or "device_code" not in data:
        raise RegisterError(_message(data) or _("Microsoft did not return a sign-in code."))
    return data


def device_poll(device_code: str) -> dict:
    """Un intento de canjear el código. Devuelve el cuerpo tal cual (``error`` o ``access_token``)."""
    _status, data = _request("POST", f"{DEVICE_AUTHORITY}/token", form={
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": DEVICE_CLIENT_ID, "device_code": device_code})
    return data


# --------------------------------------------------------------------------- registro

def register_app(access_token: str, *, name: str, redirect_uri: str, app_roles: bool = True,
                 group_claims: bool = False, require_assignment: bool = False, group_read: bool = True,
                 logout_url: str = "", secret_months: int = SECRET_MONTHS) -> dict:
    """Crea la aplicación y devuelve tenant_id, client_id, client_secret, secret_expires y avisos."""
    claims = _claims(access_token)
    tenant_id, admin_oid = claims.get("tid", ""), claims.get("oid", "")
    if not tenant_id:
        raise RegisterError(_("Could not determine the tenant of the account that signed in."))
    warnings: list[str] = []

    roles = []
    if app_roles:
        for value, label in ((ADMIN_ROLE, "StorageWeb Admin"), (USER_ROLE, "StorageWeb User")):
            roles.append({"allowedMemberTypes": ["User"], "displayName": label, "value": value,
                          "description": _("%(role)s of %(name)s", role=label, name=name),
                          "id": str(uuid.uuid4()), "isEnabled": True})
    app_body = {
        "displayName": name,
        "signInAudience": "AzureADMyOrg",
        "web": {"redirectUris": [redirect_uri], **({"logoutUrl": logout_url} if logout_url else {}),
                "implicitGrantSettings": {"enableIdTokenIssuance": False, "enableAccessTokenIssuance": False}},
        "requiredResourceAccess": [{"resourceAppId": GRAPH_APP_ID,
                                    "resourceAccess": [{"id": i, "type": "Scope"} for i in SIGN_IN_SCOPES.values()]
                                    + ([{"id": i, "type": "Role"} for i in DIRECTORY_ROLES.values()]
                                       if group_read else [])}],
        "appRoles": roles,
        "optionalClaims": _optional_claims(None, groups=group_claims),
    }
    if group_claims:
        app_body["groupMembershipClaims"] = "SecurityGroup"

    app = _graph("POST", "/applications", access_token, app_body)
    object_id, client_id = app["id"], app["appId"]
    try:
        return _finish_registration(access_token, app_body, roles, tenant_id, admin_oid, object_id, client_id,
                                    name=name, app_roles=app_roles, require_assignment=require_assignment,
                                    group_read=group_read, warnings=warnings, secret_months=secret_months)
    except RegisterError as exc:
        raise RegisterError(_("The application %(client)s was created in Entra ID, but setting it up failed: "
                              "%(error)s. Delete it in the Entra admin center (App registrations) and try again.",
                              client=client_id, error=exc)) from exc


def _secret_end(months: int) -> datetime:
    """Cuándo caduca un secreto nuevo (``auth.entra.secret_months``; las directivas del tenant pueden pedir menos)."""
    return (datetime.now(timezone.utc) + timedelta(days=30 * int(months or SECRET_MONTHS))).replace(microsecond=0)


SP_TAGS = ["WindowsAzureActiveDirectoryIntegratedApp"]    # que se vea como aplicación empresarial integrada


def _add_secret(access_token: str, object_id: str, display_name: str, months: int) -> dict:
    """Un secreto nuevo en la aplicación (``addPassword``): ``{client_secret, secret_expires}``."""
    expires = _secret_end(months)
    secret = _graph("POST", f"/applications/{object_id}/addPassword", access_token,
                    {"passwordCredential": {"displayName": display_name, "endDateTime": expires.isoformat()}})
    return {"client_secret": secret.get("secretText", ""),
            "secret_expires": secret.get("endDateTime", expires.isoformat())}


def _find_sp(access_token: str, client_id: str) -> str:
    """El id del service principal (la aplicación empresarial) de ``client_id``, o ``""`` si no tiene."""
    sps = _graph("GET", f"/servicePrincipals?$filter=appId eq '{client_id}'&$select=id", access_token).get("value")
    return sps[0]["id"] if sps else ""


def _grant_consent(access_token: str, sp_id: str, graph_sp: str) -> None:
    """Consentimiento de administrador, para todos, a los permisos de inicio de sesión (``SIGN_IN_SCOPES``)."""
    _graph("POST", "/oauth2PermissionGrants", access_token, {
        "clientId": sp_id, "consentType": "AllPrincipals", "resourceId": graph_sp, "scope": " ".join(SIGN_IN_SCOPES)})


def _finish_registration(access_token: str, app_body: dict, roles: list, tenant_id: str, admin_oid: str,
                         object_id: str, client_id: str, *, name: str, app_roles: bool, require_assignment: bool,
                         group_read: bool, warnings: list[str], secret_months: int = SECRET_MONTHS) -> dict:
    """Lo que va después de crear la aplicación: secreto, service principal, consentimiento y rol de admin."""
    secret = _add_secret(access_token, object_id, name, secret_months)

    # El service principal puede tardar unos segundos en poder crearse tras la aplicación
    sp_id = ""
    for attempt in range(5):
        status, data = _request("POST", f"{GRAPH}/servicePrincipals", token=access_token,
                                body={"appId": client_id, "tags": SP_TAGS})
        if status in (200, 201):
            sp_id = data.get("id", "")
            break
        if attempt == 4:
            warnings.append(_("The service principal could not be created: %(error)s", error=_message(data)))
        time.sleep(2)

    consented: list[str] = []  # permisos de inicio de sesión con consentimiento de administrador
    if sp_id:
        if require_assignment:
            try:
                _graph("PATCH", f"/servicePrincipals/{sp_id}", access_token, {"appRoleAssignmentRequired": True})
            except RegisterError as exc:
                warnings.append(_("Could not require assignment: %(error)s", error=exc))
        graph_sp = ""
        try:
            graph_sp = _graph_sp_id(access_token)
            _grant_consent(access_token, sp_id, graph_sp)
            consented.extend(SIGN_IN_SCOPES)
        except (RegisterError, KeyError, IndexError) as exc:
            warnings.append(_("Admin consent could not be granted (%(error)s): grant it in the portal, "
                              "API permissions → Grant admin consent.", error=exc))
        if group_read and graph_sp:
            for perm, role_id in DIRECTORY_ROLES.items():
                try:
                    _grant_role(access_token, sp_id, graph_sp, role_id)
                except RegisterError as exc:
                    warnings.append(_("%(perm)s could not be granted: %(error)s", perm=perm, error=exc))
        if app_roles and admin_oid:
            admin_role = next(r["id"] for r in roles if r["value"] == ADMIN_ROLE)
            try:
                _graph("POST", f"/servicePrincipals/{sp_id}/appRoleAssignedTo", access_token,
                       {"principalId": admin_oid, "resourceId": sp_id, "appRoleId": admin_role})
            except RegisterError as exc:
                warnings.append(_("You could not be assigned the %(role)s role: %(error)s", role=ADMIN_ROLE, error=exc))

    return {"tenant_id": tenant_id, "client_id": client_id, **secret, "group_read": bool(group_read),
            "object_id": object_id,
            "app_roles": bool(app_roles), "warnings": warnings, "signin_consent": consented,
            "portal_url": portal_url(client_id)}


# --------------------------------------------------------------------------- aplicaciones existentes

def _graph_sp_id(access_token: str) -> str:
    return _graph("GET", f"/servicePrincipals?$filter=appId eq '{GRAPH_APP_ID}'&$select=id",
                  access_token)["value"][0]["id"]


def _grant_role(access_token: str, sp_id: str, resource_sp: str, role_id: str) -> bool:
    """Concede un permiso de aplicación (consentimiento de administrador). Si ya estaba, no es error.
    Devuelve True si lo ha concedido ahora."""
    status, data = _request("POST", f"{GRAPH}/servicePrincipals/{sp_id}/appRoleAssignments", token=access_token,
                            body={"principalId": sp_id, "resourceId": resource_sp, "appRoleId": role_id})
    if status in (200, 201):
        return True
    if "already exists" in _message(data).lower():
        return False
    raise RegisterError(_message(data) or f"HTTP {status}")


def _application(access_token: str, client_id: str) -> dict:
    found = _graph("GET", f"/applications?$filter=appId eq '{client_id}'&$select=id,appId,displayName,"
                          "requiredResourceAccess,web,optionalClaims", access_token).get("value") or []
    if not found:
        raise RegisterError(_("The application %(client)s does not exist in the tenant of the account that "
                              "signed in.", client=client_id))
    return found[0]


def rotate_secret(access_token: str, client_id: str, *, secret_months: int = SECRET_MONTHS) -> dict:
    """Crea un secreto nuevo en la aplicación existente. El anterior sigue valiendo hasta que caduque."""
    app = _application(access_token, client_id)
    name = f"{app.get('displayName') or 'StorageWeb'} {datetime.now(timezone.utc):%Y-%m-%d}"
    return _add_secret(access_token, app["id"], name, secret_months)


def repair_app(access_token: str, client_id: str, *, redirect_uri: str = "", new_secret: bool = False,
               group_read: bool = True, logout_url: str = "", secret_months: int = SECRET_MONTHS) -> dict:
    """Revisa la aplicación existente y arregla lo que falte, sin tocar lo que ya está bien:

    - la Redirect URI de StorageWeb, si no está, y la URL de cierre de sesión de canal frontal (``logout_url``);
    - los claims opcionales del id_token (``email`` y ``sid``);
    - los permisos de Graph (inicio de sesión y, con ``group_read``, ``Group.Read.All`` y ``User.Read.All``);
    - la aplicación empresarial (service principal), si no existe;
    - el consentimiento de administrador de los permisos de inicio de sesión y de los de aplicación;
    - con ``new_secret``, un secreto nuevo (el anterior sigue valiendo hasta que caduque).

    Cada arreglo es independiente: si uno falla, se apunta en ``warnings`` y se sigue con los demás.
    Devuelve ``{"fixed": [...], "warnings": [...], "client_secret"?, "secret_expires"?}``.
    """
    app = _application(access_token, client_id)
    fixed: list[str] = []
    warnings: list[str] = []
    result: dict = {"fixed": fixed, "warnings": warnings}

    def step(what: str, action) -> None:
        try:
            action()
        except (RegisterError, KeyError, IndexError, TypeError) as exc:
            warnings.append(_("%(what)s: %(error)s", what=what, error=exc))

    def redirect() -> None:
        web = app.get("web") or {}
        uris = list(web.get("redirectUris") or [])
        if redirect_uri and redirect_uri not in uris:
            _graph("PATCH", f"/applications/{app['id']}", access_token, {"web": {"redirectUris": uris + [redirect_uri]}})
            fixed.append(_("Redirect URI added: %(uri)s", uri=redirect_uri))
    step(_("Redirect URI"), redirect)

    def logout() -> None:
        if logout_url and (app.get("web") or {}).get("logoutUrl") != logout_url:
            _graph("PATCH", f"/applications/{app['id']}", access_token, {"web": {"logoutUrl": logout_url}})
            fixed.append(_("Front-channel logout URL set: %(uri)s", uri=logout_url))
    step(_("Front-channel logout URL"), logout)

    def optional_claims() -> None:
        current = app.get("optionalClaims") or {}
        has_groups = any(c.get("name") == "groups" for c in current.get("idToken") or [])
        wanted = _optional_claims(current, groups=has_groups)
        if wanted is not None:
            _graph("PATCH", f"/applications/{app['id']}", access_token, {"optionalClaims": wanted})
            fixed.append(_("Optional claims added to the ID token (email, sid)"))
    step(_("Optional claims"), optional_claims)

    def permissions() -> None:
        access, graph = _graph_access(app)
        have = {(a.get("id"), a.get("type")) for a in graph["resourceAccess"]}
        wanted = [(i, "Scope") for i in SIGN_IN_SCOPES.values()] + (
            [(i, "Role") for i in DIRECTORY_ROLES.values()] if group_read else [])
        missing = [w for w in wanted if w not in have]
        if missing:
            graph["resourceAccess"] += [{"id": i, "type": kind} for i, kind in missing]
            _graph("PATCH", f"/applications/{app['id']}", access_token, {"requiredResourceAccess": access})
            fixed.append(_("Missing Microsoft Graph permissions added to the application"))
    step(_("Permissions"), permissions)

    sp = {"id": ""}

    def service_principal() -> None:
        sp["id"] = _find_sp(access_token, client_id)
        if not sp["id"]:
            sp["id"] = _graph("POST", "/servicePrincipals", access_token, {"appId": client_id, "tags": SP_TAGS})["id"]
            fixed.append(_("Enterprise application (service principal) created"))
    step(_("Enterprise application"), service_principal)

    if sp["id"]:
        graph_sp = {"id": ""}

        def consent() -> None:
            graph_sp["id"] = _graph_sp_id(access_token)
            grants = _graph("GET", f"/oauth2PermissionGrants?$filter=clientId eq '{sp['id']}' and "
                                   f"resourceId eq '{graph_sp['id']}'", access_token).get("value") or []
            grant = next((g for g in grants if g.get("consentType") == "AllPrincipals"), None)
            scopes = set(SIGN_IN_SCOPES)
            if grant is None:
                _grant_consent(access_token, sp["id"], graph_sp["id"])
                fixed.append(_("Admin consent granted for signing in"))
            elif not scopes <= set((grant.get("scope") or "").split()):
                merged = " ".join(sorted(set((grant.get("scope") or "").split()) | scopes))
                _graph("PATCH", f"/oauth2PermissionGrants/{grant['id']}", access_token, {"scope": merged})
                fixed.append(_("Admin consent granted for signing in"))
            result["signin_consent"] = list(SIGN_IN_SCOPES)  # ya estaba o se acaba de dar
        step(_("Admin consent"), consent)

        if group_read and graph_sp["id"]:
            for perm, role_id in DIRECTORY_ROLES.items():
                def grant(perm=perm, role_id=role_id) -> None:
                    if _grant_role(access_token, sp["id"], graph_sp["id"], role_id):
                        fixed.append(_("Application permission %(perm)s granted", perm=perm))
                step(perm, grant)

    if new_secret:
        def secret() -> None:
            result.update(rotate_secret(access_token, client_id, secret_months=secret_months))
            fixed.append(_("New client secret created"))
        step(_("Client secret"), secret)
    return result


def _graph_access(app: dict) -> tuple[list, dict]:
    """``(requiredResourceAccess, la entrada de Microsoft Graph)`` de una aplicación; la de Graph se añade (vacía) a
    la lista si no estaba, para sumarle permisos y enviar la lista entera."""
    access = app.get("requiredResourceAccess") or []
    graph = next((r for r in access if r.get("resourceAppId") == GRAPH_APP_ID), None)
    if graph is None:
        graph = {"resourceAppId": GRAPH_APP_ID, "resourceAccess": []}
        access.append(graph)
    return access, graph


def grant_group_read(access_token: str, client_id: str) -> None:
    """Añade los permisos de aplicación de lectura del directorio (``Group.Read.All`` y ``User.Read.All``) a una
    aplicación existente y les da el consentimiento."""
    app = _application(access_token, client_id)
    access, graph = _graph_access(app)
    have = {a.get("id") for a in graph["resourceAccess"]}
    missing = [i for i in DIRECTORY_ROLES.values() if i not in have]
    if missing:
        graph["resourceAccess"] += [{"id": i, "type": "Role"} for i in missing]
        _graph("PATCH", f"/applications/{app['id']}", access_token, {"requiredResourceAccess": access})
    sp_id = _find_sp(access_token, client_id) or _graph("POST", "/servicePrincipals", access_token,
                                                         {"appId": client_id})["id"]
    graph_sp = _graph_sp_id(access_token)
    for role_id in DIRECTORY_ROLES.values():
        _grant_role(access_token, sp_id, graph_sp, role_id)

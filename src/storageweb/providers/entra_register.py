"""Registro automático de StorageWeb como aplicación de Entra ID.

El administrador inicia sesión con el **flujo de código de dispositivo** (abre
``microsoft.com/devicelogin`` en cualquier navegador y escribe un código) contra un cliente público
de Microsoft. Con ese token delegado se llama a Microsoft Graph para:

1. crear la aplicación (``/applications``): Redirect URI, permisos ``openid profile email
   User.Read``, App Roles ``StorageWeb.Admin`` y ``StorageWeb.User`` y, si se pide, el claim de grupos;
2. crearle un secreto (``addPassword``);
3. crear su *service principal* y, si se pide, exigir asignación;
4. dar el consentimiento de administrador a los permisos (``oauth2PermissionGrants``);
5. asignar al administrador que la registra el rol ``StorageWeb.Admin``.

Los pasos 4 y 5 son de mejor esfuerzo: si fallan, la aplicación ya es usable y se devuelve un aviso
con el enlace al portal. Solo usa la biblioteca estándar.

Inspirado en el asistente «Register in Azure» de ServiceSentry.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from ..i18n import _
from .base import MS_LOGIN

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
# Permiso de aplicación de Graph para leer los nombres de los grupos (id fijo en todos los tenants)
GROUP_READ_ALL = "5b567255-7703-4780-807c-7be8301ae99b"
SECRET_MONTHS = 24
TIMEOUT = 20


class RegisterError(Exception):
    pass


# --------------------------------------------------------------------------- HTTP

def _request(method: str, url: str, *, token: str | None = None, form: dict | None = None,
             body: dict | None = None) -> tuple[int, dict]:
    """Petición HTTP que devuelve (estado, JSON). Los errores HTTP no lanzan: devuelven su cuerpo."""
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
    except (OSError, ValueError) as exc:
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
        payload = access_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
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
                 logout_url: str = "") -> dict:
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
                                    + ([{"id": GROUP_READ_ALL, "type": "Role"}] if group_read else [])}],
        "appRoles": roles,
    }
    if group_claims:
        app_body["groupMembershipClaims"] = "SecurityGroup"
        app_body["optionalClaims"] = {"idToken": [{"name": "groups", "essential": False}]}

    app = _graph("POST", "/applications", access_token, app_body)
    object_id, client_id = app["id"], app["appId"]

    expires = (datetime.now(timezone.utc) + timedelta(days=30 * SECRET_MONTHS)).replace(microsecond=0)
    secret = _graph("POST", f"/applications/{object_id}/addPassword", access_token,
                    {"passwordCredential": {"displayName": name, "endDateTime": expires.isoformat()}})

    # El service principal puede tardar unos segundos en poder crearse tras la aplicación
    sp_id = ""
    for attempt in range(5):
        status, data = _request("POST", f"{GRAPH}/servicePrincipals", token=access_token,
                                body={"appId": client_id, "tags": ["WindowsAzureActiveDirectoryIntegratedApp"]})
        if status in (200, 201):
            sp_id = data.get("id", "")
            break
        if attempt == 4:
            warnings.append(_("The service principal could not be created: %(error)s", error=_message(data)))
        time.sleep(2)

    if sp_id:
        if require_assignment:
            try:
                _graph("PATCH", f"/servicePrincipals/{sp_id}", access_token, {"appRoleAssignmentRequired": True})
            except RegisterError as exc:
                warnings.append(_("Could not require assignment: %(error)s", error=exc))
        graph_sp = ""
        try:
            graph_sp = _graph_sp_id(access_token)
            _graph("POST", "/oauth2PermissionGrants", access_token, {
                "clientId": sp_id, "consentType": "AllPrincipals", "resourceId": graph_sp,
                "scope": " ".join(SIGN_IN_SCOPES)})
        except (RegisterError, KeyError, IndexError) as exc:
            warnings.append(_("Admin consent could not be granted (%(error)s): grant it in the portal, "
                              "API permissions → Grant admin consent.", error=exc))
        if group_read and graph_sp:
            try:
                _grant_role(access_token, sp_id, graph_sp, GROUP_READ_ALL)
            except RegisterError as exc:
                warnings.append(_("Reading group names (Group.Read.All) could not be granted: %(error)s", error=exc))
        if app_roles and admin_oid:
            admin_role = next(r["id"] for r in roles if r["value"] == ADMIN_ROLE)
            try:
                _graph("POST", f"/servicePrincipals/{sp_id}/appRoleAssignedTo", access_token,
                       {"principalId": admin_oid, "resourceId": sp_id, "appRoleId": admin_role})
            except RegisterError as exc:
                warnings.append(_("You could not be assigned the %(role)s role: %(error)s", role=ADMIN_ROLE, error=exc))

    return {"tenant_id": tenant_id, "client_id": client_id, "client_secret": secret.get("secretText", ""),
            "group_read": bool(group_read),
            "secret_expires": secret.get("endDateTime", expires.isoformat()), "object_id": object_id,
            "app_roles": bool(app_roles), "warnings": warnings,
            "portal_url": ("https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade"
                           f"/~/Overview/appId/{client_id}")}


# --------------------------------------------------------------------------- aplicaciones existentes

def _graph_sp_id(access_token: str) -> str:
    return _graph("GET", f"/servicePrincipals?$filter=appId eq '{GRAPH_APP_ID}'&$select=id",
                  access_token)["value"][0]["id"]


def _grant_role(access_token: str, sp_id: str, resource_sp: str, role_id: str) -> None:
    """Concede un permiso de aplicación (consentimiento de administrador). Si ya estaba, no es error."""
    status, data = _request("POST", f"{GRAPH}/servicePrincipals/{sp_id}/appRoleAssignments", token=access_token,
                            body={"principalId": sp_id, "resourceId": resource_sp, "appRoleId": role_id})
    if status not in (200, 201) and "already exists" not in _message(data).lower():
        raise RegisterError(_message(data) or f"HTTP {status}")


def _application(access_token: str, client_id: str) -> dict:
    found = _graph("GET", f"/applications?$filter=appId eq '{client_id}'&$select=id,appId,displayName,"
                          "requiredResourceAccess", access_token).get("value") or []
    if not found:
        raise RegisterError(_("The application %(client)s does not exist in the tenant of the account that "
                              "signed in.", client=client_id))
    return found[0]


def rotate_secret(access_token: str, client_id: str) -> dict:
    """Crea un secreto nuevo en la aplicación existente. El anterior sigue valiendo hasta que caduque."""
    app = _application(access_token, client_id)
    expires = (datetime.now(timezone.utc) + timedelta(days=30 * SECRET_MONTHS)).replace(microsecond=0)
    secret = _graph("POST", f"/applications/{app['id']}/addPassword", access_token,
                    {"passwordCredential": {"displayName": f"{app.get('displayName') or 'StorageWeb'} "
                                                           f"{datetime.now(timezone.utc):%Y-%m-%d}",
                                            "endDateTime": expires.isoformat()}})
    return {"client_secret": secret.get("secretText", ""),
            "secret_expires": secret.get("endDateTime", expires.isoformat())}


def grant_group_read(access_token: str, client_id: str) -> None:
    """Añade Group.Read.All (permiso de aplicación) a una aplicación existente y le da el consentimiento."""
    app = _application(access_token, client_id)
    access = app.get("requiredResourceAccess") or []
    graph = next((r for r in access if r.get("resourceAppId") == GRAPH_APP_ID), None)
    if graph is None:
        graph = {"resourceAppId": GRAPH_APP_ID, "resourceAccess": []}
        access.append(graph)
    if not any(a.get("id") == GROUP_READ_ALL for a in graph["resourceAccess"]):
        graph["resourceAccess"].append({"id": GROUP_READ_ALL, "type": "Role"})
        _graph("PATCH", f"/applications/{app['id']}", access_token, {"requiredResourceAccess": access})
    sps = _graph("GET", f"/servicePrincipals?$filter=appId eq '{client_id}'&$select=id", access_token).get("value")
    sp_id = sps[0]["id"] if sps else _graph("POST", "/servicePrincipals", access_token, {"appId": client_id})["id"]
    _grant_role(access_token, sp_id, _graph_sp_id(access_token), GROUP_READ_ALL)

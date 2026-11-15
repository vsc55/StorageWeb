"""Registro automático en Entra ID (Graph simulado: se comprueba qué se pide y en qué orden)."""
import base64
import json

import pytest

from storageweb.providers.entra import register as er


def _token(**claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"h.{payload}.s"


@pytest.fixture
def graph(monkeypatch):
    """Registra cada petición y responde según la ruta."""
    calls = []
    answers = {}

    def fake(method, url, *, token=None, form=None, body=None):
        path = url.replace(er.GRAPH, "")
        calls.append((method, path, body or form))
        for (m, prefix), answer in answers.items():
            if m == method and path.startswith(prefix):
                return answer(body) if callable(answer) else answer
        return 200, {}

    answers[("POST", "/applications/")] = (200, {"secretText": "s3cr3t", "endDateTime": "2028-11-13T00:00:00Z"})
    answers[("POST", "/applications")] = (201, {"id": "obj-1", "appId": "client-1"})
    answers[("POST", "/servicePrincipals/")] = (201, {})
    answers[("POST", "/servicePrincipals")] = (201, {"id": "sp-1"})
    answers[("GET", "/servicePrincipals?")] = (200, {"value": [{"id": "graph-sp"}]})
    answers[("POST", "/oauth2PermissionGrants")] = (201, {})
    monkeypatch.setattr(er, "_request", fake)
    monkeypatch.setattr(er.time, "sleep", lambda s: None)
    return calls, answers


def test_register_full(graph):
    calls, _answers = graph
    result = er.register_app(_token(tid="tenant-1", oid="admin-oid"), name="Archivos",
                             redirect_uri="https://files.example.com/auth/entra/callback",
                             group_claims=True, require_assignment=True)
    assert result["tenant_id"] == "tenant-1" and result["client_id"] == "client-1"
    assert result["signin_consent"] == ["openid", "profile", "email", "User.Read"]
    assert result["client_secret"] == "s3cr3t" and result["warnings"] == []

    app = calls[0][2]
    assert calls[0][:2] == ("POST", "/applications")
    assert app["web"]["redirectUris"] == ["https://files.example.com/auth/entra/callback"]
    assert app["signInAudience"] == "AzureADMyOrg" and app["groupMembershipClaims"] == "SecurityGroup"
    assert {r["value"] for r in app["appRoles"]} == {"StorageWeb.Admin", "StorageWeb.User"}
    paths = [(m, p.split("?")[0]) for m, p, _b in calls]
    assert ("PATCH", "/servicePrincipals/sp-1") in paths                       # asignación requerida
    grant = next(b for m, p, b in calls if p == "/oauth2PermissionGrants")
    assert grant["consentType"] == "AllPrincipals" and grant["scope"] == "openid profile email User.Read"
    assign = next(b for m, p, b in calls if p.endswith("/appRoleAssignedTo"))
    admin_role = next(r["id"] for r in app["appRoles"] if r["value"] == "StorageWeb.Admin")
    assert assign == {"principalId": "admin-oid", "resourceId": "sp-1", "appRoleId": admin_role}


def test_register_minimal_and_best_effort_warnings(graph):
    calls, answers = graph
    answers[("POST", "/oauth2PermissionGrants")] = (403, {"error": {"message": "Insufficient privileges"}})
    result = er.register_app(_token(tid="t", oid="o"), name="X", redirect_uri="https://x/cb", app_roles=False)
    assert result["client_secret"] == "s3cr3t"
    assert len(result["warnings"]) == 1 and "Insufficient privileges" in result["warnings"][0]
    assert not any(p.endswith("/appRoleAssignedTo") for _m, p, _b in calls)
    assert "groupMembershipClaims" not in calls[0][2] and calls[0][2]["appRoles"] == []


def test_register_fails_without_tenant(graph):
    with pytest.raises(er.RegisterError):
        er.register_app("no-es-un-jwt", name="X", redirect_uri="https://x/cb")


def test_register_app_creation_error(graph):
    _calls, answers = graph
    answers[("POST", "/applications")] = (403, {"error": {"message": "Authorization_RequestDenied"}})
    with pytest.raises(er.RegisterError, match="Authorization_RequestDenied"):
        er.register_app(_token(tid="t"), name="X", redirect_uri="https://x/cb")


def test_device_start_and_poll(monkeypatch):
    sent = []

    def fake(method, url, *, token=None, form=None, body=None):
        sent.append((url, form))
        if url.endswith("/devicecode"):
            return 200, {"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin"}
        return 400, {"error": "authorization_pending"}

    monkeypatch.setattr(er, "_request", fake)
    assert er.device_start()["user_code"] == "ABCD-1234"
    assert "Application.ReadWrite.All" in sent[0][1]["scope"] and sent[0][1]["client_id"] == er.DEVICE_CLIENT_ID
    assert er.device_poll("dc") == {"error": "authorization_pending"}
    assert sent[1][1]["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"


def test_graph_urls_are_encoded_before_sending(monkeypatch):
    """Las consultas de Graph llevan espacios y comillas ($filter=appId eq '…'): Python 3.14 rechaza esas URLs
    sin codificar. Se prueba hasta la petición HTTP (los demás tests sustituyen _request entero)."""
    import io
    import json as _json
    sent = []

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent.append(req.full_url)
        return Resp(_json.dumps({"value": [{"id": "sp-graph"}]}).encode())

    monkeypatch.setattr(er.urllib.request, "urlopen", fake_urlopen)
    assert er._graph_sp_id("token") == "sp-graph"
    assert " " not in sent[0] and "appId%20eq%20'00000003-0000-0000-c000-000000000000'" in sent[0]
    assert "$filter=" in sent[0] and "&$select=id" in sent[0]
    # Lo ya codificado no se codifica dos veces (la búsqueda de grupos codifica el texto antes)
    er._request("GET", f"{er.GRAPH}/groups?$filter=startswith(displayName,'caf%C3%A9')")
    assert sent[-1].endswith("startswith(displayName,'caf%C3%A9')")


def test_connection_errors_become_register_errors(monkeypatch):
    import http.client

    def broken(req, timeout=None):
        raise http.client.InvalidURL("bad")

    monkeypatch.setattr(er.urllib.request, "urlopen", broken)
    with pytest.raises(er.RegisterError):
        er._request("GET", f"{er.GRAPH}/x")


def test_failure_after_creating_the_app_names_it(graph, monkeypatch):
    """Si algo falla después de crear la aplicación, el mensaje dice cuál quedó creada para borrarla."""
    original = er._graph

    def failing(method, path, token, body=None, ok=(200, 201, 204)):
        if path.endswith("/addPassword"):
            raise er.RegisterError("boom")
        return original(method, path, token, body, ok)

    monkeypatch.setattr(er, "_graph", failing)
    with pytest.raises(er.RegisterError) as exc:
        er.register_app(_token(tid="t", oid="o"), name="StorageWeb", redirect_uri="https://x/auth/entra/callback")
    assert "boom" in str(exc.value) and "Entra" in str(exc.value)



def test_repair_fixes_only_what_is_missing(graph):
    calls, answers = graph
    app = {"id": "obj-1", "appId": "c1", "displayName": "StorageWeb", "web": {"redirectUris": ["https://old/cb"]},
           "requiredResourceAccess": [{"resourceAppId": er.GRAPH_APP_ID,
                                       "resourceAccess": [{"id": er.SIGN_IN_SCOPES["openid"], "type": "Scope"}]}]}
    answers[("GET", "/applications?")] = (200, {"value": [app]})
    generic = answers.pop(("GET", "/servicePrincipals?"))  # la consulta concreta tiene que ir antes que la genérica
    answers[("GET", "/servicePrincipals?$filter=appId eq 'c1'")] = (200, {"value": [{"id": "sp-1"}]})
    answers[("GET", "/servicePrincipals?")] = generic
    answers[("GET", "/oauth2PermissionGrants?")] = (200, {"value": []})
    answers[("POST", "/servicePrincipals/sp-1/appRoleAssignments")] = (201, {})
    answers[("POST", "/applications/obj-1/addPassword")] = (200, {"secretText": "nuevo", "endDateTime": "2028-01-01"})
    result = er.repair_app(_token(tid="t"), "c1", redirect_uri="https://files/auth/entra/callback", new_secret=True,
                           logout_url="https://files/auth/entra/frontchannel-logout")
    assert result["warnings"] == []
    assert result["client_secret"]  # el secreto nuevo (el Graph simulado responde con uno fijo)
    patches = [b for m, p, b in calls if m == "PATCH" and p == "/applications/obj-1"]
    assert {"web": {"redirectUris": ["https://old/cb", "https://files/auth/entra/callback"]}} in patches
    access = next(b for b in patches if "requiredResourceAccess" in b)["requiredResourceAccess"][0]["resourceAccess"]
    assert {(a["id"], a["type"]) for a in access} >= {(i, "Scope") for i in er.SIGN_IN_SCOPES.values()} | {
        (er.GROUP_READ_ALL, "Role"), (er.USER_READ_ALL, "Role")}
    assert {"web": {"logoutUrl": "https://files/auth/entra/frontchannel-logout"}} in patches
    claims = next(b for b in patches if "optionalClaims" in b)["optionalClaims"]["idToken"]
    assert {c["name"] for c in claims} == {"email", "sid"}
    grant = next(b for m, p, b in calls if m == "POST" and p == "/oauth2PermissionGrants")
    assert grant["consentType"] == "AllPrincipals" and grant["clientId"] == "sp-1"
    # redirect, cierre de sesión, claims, permisos, consentimiento, Group.Read.All, User.Read.All, secreto
    assert len(result["fixed"]) == 8


def test_repair_leaves_a_correct_app_alone(graph):
    calls, answers = graph
    full = [{"id": i, "type": "Scope"} for i in er.SIGN_IN_SCOPES.values()] + [
        {"id": er.GROUP_READ_ALL, "type": "Role"}, {"id": er.USER_READ_ALL, "type": "Role"}]
    app = {"id": "obj-1", "appId": "c1", "web": {"redirectUris": ["https://files/cb"], "logoutUrl": "https://files/fc"},
           "requiredResourceAccess": [{"resourceAppId": er.GRAPH_APP_ID, "resourceAccess": full}],
           "optionalClaims": {"idToken": [{"name": "email"}, {"name": "sid"}, {"name": "groups"}]}}
    answers[("GET", "/applications?")] = (200, {"value": [app]})
    answers[("GET", "/oauth2PermissionGrants?")] = (200, {"value": [
        {"id": "g1", "consentType": "AllPrincipals", "scope": "openid profile email User.Read"}]})
    answers[("POST", "/servicePrincipals/")] = (400, {"error": {"message": "Permission already exists"}})
    result = er.repair_app(_token(tid="t"), "c1", redirect_uri="https://files/cb", logout_url="https://files/fc")
    assert result["fixed"] == [] and result["warnings"] == []
    assert result["signin_consent"] == list(er.SIGN_IN_SCOPES)  # ya estaba: se confirma
    assert not [c for c in calls if c[0] in ("PATCH", "POST") and c[1].startswith("/applications")]


def test_repair_keeps_going_when_one_step_fails(graph):
    calls, answers = graph
    answers[("GET", "/applications?")] = (200, {"value": [{"id": "obj-1", "appId": "c1", "web": {"redirectUris": []},
                                                            "requiredResourceAccess": []}]})
    answers[("PATCH", "/applications/obj-1")] = (403, {"error": {"message": "Insufficient privileges"}})
    answers[("GET", "/oauth2PermissionGrants?")] = (200, {"value": []})
    result = er.repair_app(_token(tid="t"), "c1", redirect_uri="https://files/cb")
    assert any("Insufficient privileges" in w for w in result["warnings"])
    assert any(m == "POST" and p == "/oauth2PermissionGrants" for m, p, _b in calls), "sigue con el consentimiento"

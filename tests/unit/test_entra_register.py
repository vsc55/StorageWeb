"""Registro automático en Entra ID (Graph simulado: se comprueba qué se pide y en qué orden)."""
import base64
import json

import pytest

from storageweb.providers import entra_register as er


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

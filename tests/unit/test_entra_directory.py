"""Nombres de grupos de Entra ID, renovación del secreto y lectura de grupos (Microsoft simulado)."""
import pytest

from storageweb.providers import entra_directory as ed
from storageweb.providers import entra_register as er
from storageweb.providers import oauth2

ECFG = {"tenant_id": "t1", "client_id": "c1", "client_secret": "s", "timeout_seconds": 5}
G1, G2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def graph(monkeypatch):
    calls = []
    answers = {}
    tokens = []

    def fake(method, url, *, token=None, form=None, body=None):
        path = url.replace(er.GRAPH, "")
        calls.append((method, path, body))
        for (m, prefix), answer in answers.items():
            if m == method and path.startswith(prefix):
                return answer
        return 200, {}

    def token_post(url, data, timeout):
        tokens.append(data)
        return {"access_token": "app-token"}

    monkeypatch.setattr(er, "_request", fake)
    monkeypatch.setattr(ed, "_request", fake)
    monkeypatch.setattr(oauth2, "_http_post", token_post)
    ed.clear_cache()
    yield calls, answers, tokens
    ed.clear_cache()


def test_names_for_with_cache(graph):
    calls, answers, tokens = graph
    answers[("POST", "/directoryObjects/getByIds")] = (200, {"value": [{"id": G1, "displayName": "Sistemas"}]})
    assert ed.names_for(ECFG, [G1, G2.upper(), "StorageWeb.Admin"]) == {G1: "Sistemas"}
    assert sorted(calls[0][2]["ids"]) == sorted([G1, G2]) and calls[0][2]["types"] == ["group"]
    assert "StorageWeb.Admin" not in str(calls[0][2]["ids"])        # los App Roles no se consultan
    assert ed.names_for(ECFG, [G1, G2]) == {G1: "Sistemas"} and len(calls) == 1   # caché (también del «no existe»)
    assert len(tokens) == 1 and tokens[0]["grant_type"] == "client_credentials"


def test_names_for_not_configured_or_forbidden(graph):
    calls, answers, _tokens = graph
    assert ed.names_for({"tenant_id": "t1"}, [G1]) == {} and calls == []
    answers[("POST", "/directoryObjects/getByIds")] = (403, {"error": {"message": "Insufficient privileges"}})
    assert ed.names_for(ECFG, [G1]) == {}


def test_search_groups(graph):
    calls, answers, _tokens = graph
    answers[("GET", "/groups?")] = (200, {"value": [{"id": G2.upper(), "displayName": "Ventas"},
                                                    {"id": G1, "displayName": "Administración"}]})
    assert ed.search_groups(ECFG, "a") == []                        # mínimo dos letras
    found = ed.search_groups(ECFG, "Ad'm")
    assert [g["name"] for g in found] == ["Administración", "Ventas"] and found[1]["id"] == G2
    assert "startswith(displayName,'Ad%27%27m')" in calls[0][1]
    assert ed.names_for(ECFG, [G2]) == {G2: "Ventas"} and len(calls) == 1      # la búsqueda alimenta la caché


def test_rotate_secret(graph):
    calls, answers, _tokens = graph
    answers[("GET", "/applications?")] = (200, {"value": [{"id": "obj-1", "appId": "c1", "displayName": "Archivos"}]})
    answers[("POST", "/applications/obj-1/addPassword")] = (200, {"secretText": "nuevo", "endDateTime": "2029-01-01T00:00:00Z"})
    assert er.rotate_secret("tok", "c1") == {"client_secret": "nuevo", "secret_expires": "2029-01-01T00:00:00Z"}
    answers[("GET", "/applications?")] = (200, {"value": []})
    with pytest.raises(er.RegisterError, match="no existe"):
        er.rotate_secret("tok", "c1")


def test_grant_group_read_adds_permission_once(graph):
    calls, answers, _tokens = graph
    answers[("GET", "/applications?")] = (200, {"value": [{"id": "obj-1", "appId": "c1", "requiredResourceAccess": [
        {"resourceAppId": er.GRAPH_APP_ID, "resourceAccess": [{"id": er.SIGN_IN_SCOPES["openid"], "type": "Scope"}]}]}]})
    answers[("GET", "/servicePrincipals?$filter=appId eq 'c1'")] = (200, {"value": [{"id": "sp-app"}]})
    answers[("GET", "/servicePrincipals?$filter=appId eq '00000003")] = (200, {"value": [{"id": "sp-graph"}]})
    answers[("POST", "/servicePrincipals/sp-app/appRoleAssignments")] = (
        400, {"error": {"message": "Permission being assigned already exists on the object"}})
    er.grant_group_read("tok", "c1")                                 # «ya existe» no es error
    patch = next(b for m, p, b in calls if m == "PATCH")
    graph_access = patch["requiredResourceAccess"][0]["resourceAccess"]
    assert {"id": er.GROUP_READ_ALL, "type": "Role"} in graph_access and len(graph_access) == 2
    assign = next(b for m, p, b in calls if p.endswith("/appRoleAssignments"))
    assert assign == {"principalId": "sp-app", "resourceId": "sp-graph", "appRoleId": er.GROUP_READ_ALL}

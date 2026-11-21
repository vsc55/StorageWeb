"""El cliente de Graph de Personas → Importar: la página siguiente se compone aquí con el $skiptoken (nunca con la
dirección que llegue de fuera) y quién puede entrar si la aplicación exige asignación (miembros directos de los
grupos asignados)."""
from __future__ import annotations

import pytest

from storageweb.providers.entra import directory as d
from tests.sso_helpers import entra_cfg


@pytest.fixture
def graph(monkeypatch):
    asked = []
    answers = {}

    def fake(method, url, token=None, body=None, form=None):
        asked.append(url)
        for prefix, answer in answers.items():
            if url.startswith(prefix):
                return answer
        return 404, {}

    monkeypatch.setattr(d, "_request", fake)
    monkeypatch.setattr(d, "_app_token", lambda ecfg: "tok")
    d.clear_cache()
    return asked, answers


def test_next_page_uses_only_the_skiptoken(graph):
    asked, answers = graph
    answers[f"{d.GRAPH}/users?"] = (200, {"value": [{"id": "a"}],
                                          "@odata.nextLink": "https://evil.example/steal?$skiptoken=ABC123&x=1"})
    users, following = d.list_users(entra_cfg(), "", 50)
    assert users == [{"id": "a"}] and following == "ABC123"
    d.list_users(entra_cfg(), following, 50)
    assert asked[-1].startswith(f"{d.GRAPH}/users?") and "$skiptoken=ABC123" in asked[-1]
    assert "evil.example" not in "".join(asked)
    assert d.list_users(entra_cfg(), "a b<script>", 50) is None                  # un cursor que no lo parece


def test_who_can_sign_in_when_assignment_is_required(graph):
    _asked, answers = graph
    answers[f"{d.GRAPH}/servicePrincipals?"] = (200, {"value": [{"id": "sp1", "appRoleAssignmentRequired": True}]})
    answers[f"{d.GRAPH}/servicePrincipals/sp1/appRoleAssignedTo"] = (200, {"value": [
        {"principalId": "U-DIRECT", "principalType": "User"}, {"principalId": "g1", "principalType": "Group"}]})
    answers[f"{d.GRAPH}/groups/g1/members"] = (200, {"value": [{"id": "U-MEMBER"}]})
    info = d.assignment(entra_cfg())
    assert d.assigned("u-direct", info) and d.assigned("U-MEMBER", info) and not d.assigned("otra", info)
    d.clear_cache()
    answers[f"{d.GRAPH}/servicePrincipals?"] = (200, {"value": [{"id": "sp1", "appRoleAssignmentRequired": False}]})
    assert d.assigned("cualquiera", d.assignment(entra_cfg()))
    d.clear_cache()
    answers[f"{d.GRAPH}/servicePrincipals?"] = (403, {"error": {"message": "Insufficient privileges"}})
    assert d.assignment(entra_cfg()) is None                                    # sin permiso: no se sabe

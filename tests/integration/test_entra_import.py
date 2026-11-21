"""Personas → Importar de Microsoft Entra ID: buscar en el directorio e importar antes de que entren, con el mismo
nombre e identificador que les daría su primer inicio de sesión (que luego enlaza con esa cuenta). Graph simulado."""
from __future__ import annotations

import pytest

from storageweb.db.repositories import users
from storageweb.providers.entra import directory as entra_directory
from storageweb.web.context import get_db
from tests.helpers import add_user, get_csrf, login
from tests.integration.test_entra_directory_sync import _login
from tests.integration.test_mfa import last_audit

G_IT = "22222222-2222-2222-2222-222222222222"
JUAN = {"id": "oid-juan", "displayName": "Juan Pérez", "userPrincipalName": "Juan@Contoso.com",
        "mail": "juan@contoso.com", "accountEnabled": True, "jobTitle": "Técnico", "department": "IT"}
PEDRO = {"id": "oid-pedro", "displayName": "Pedro Ruiz", "userPrincipalName": "pedro@contoso.com",
         "mail": "pedro@contoso.com", "accountEnabled": True}


@pytest.fixture
def graph(monkeypatch):
    class Graph:
        people = {"oid-juan": JUAN, "oid-pedro": PEDRO}
        groups: list | None = [G_IT]
        searched: list = []

    g = Graph()
    g.searched = []
    monkeypatch.setattr(entra_directory, "search_users",
                        lambda ecfg, text, limit=25: (g.searched.append(text), [
                            u for u in g.people.values()
                            if u["displayName"].lower().startswith(text.lower())
                            or u["userPrincipalName"].lower().startswith(text.lower())])[1])
    monkeypatch.setattr(entra_directory, "get_user", lambda ecfg, oid: g.people.get(oid))
    monkeypatch.setattr(entra_directory, "member_groups", lambda ecfg, oid: g.groups)
    g.assignment = {"required": False, "users": set()}
    monkeypatch.setattr(entra_directory, "assignment", lambda ecfg: g.assignment)

    def pages(ecfg, skiptoken="", page_size=50):
        everyone = sorted(g.people.values(), key=lambda u: u["displayName"])
        start = int(skiptoken or 0)
        chunk = everyone[start:start + 1]                       # una por página: se ve la carga al bajar
        return chunk, (str(start + 1) if start + 1 < len(everyone) else "")
    monkeypatch.setattr(entra_directory, "list_users", pages)
    return g


def _admin(app):
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return client, get_csrf(client, "/admin/users")


def test_search_and_import_before_they_sign_in(entra_app, graph, token_endpoint):
    app = entra_app(role_mappings={G_IT: "admin"})
    client, token = _admin(app)
    listing = client.get("/admin/users").get_data(as_text=True)
    assert "Importar de Entra ID" in listing and "/admin/users/import?source=entra" in listing
    page = client.get("/admin/users/import?source=entra&q=ju").get_data(as_text=True)
    assert "Juan Pérez" in page and "juan@contoso.com" in page and "Técnico · IT" in page and "Pedro" not in page
    assert graph.searched == ["ju"]
    resp = client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "q": "ju",
                                                    "external_id": "oid-juan"})
    assert resp.status_code == 302 and "/admin/users/import" in resp.location
    with app.app_context():
        juan = users.get_by_external(get_db(), "entra", "oid-juan")
    # El mismo nombre que le daría Microsoft (en minúsculas), su rol por el mapeo de grupos y sus grupos ya
    assert juan["username"] == "juan@contoso.com" and juan["role"] == "admin" and G_IT in juan["external_groups"]
    assert juan["display_name"] == "Juan Pérez"
    assert last_audit(app, "user_imported")["detail"] == "entra:admin created"
    again = client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-juan"},
                        follow_redirects=True).get_data(as_text=True)
    assert "ya está importada" in again
    assert "ya importada" in client.get("/admin/users/import?source=entra&q=ju").get_data(as_text=True)
    # Su primer inicio de sesión entra en ESA cuenta (no crea otra)
    person = app.test_client()
    assert _login(person, token_endpoint).status_code == 302
    with app.app_context():
        assert len([u for u in users.list_all(get_db()) if u["source"] == "entra"]) == 1


def test_live_search_returns_only_the_results(entra_app, graph):
    app = entra_app()
    client, _token = _admin(app)
    page = client.get("/admin/users/import").get_data(as_text=True)
    assert 'id="import-results"' in page and "/static/js/admin/user-import.js" in page
    part = client.get("/admin/users/import?source=entra&q=ju&partial=1").get_data(as_text=True)
    assert "Juan Pérez" in part and "<html" not in part and 'name="external_id" value="oid-juan"' in part
    assert client.get("/admin/users/import?q=j&partial=1").get_data(as_text=True).strip() == ""   # menos de 2 letras


def test_the_browser_only_sends_the_identifier(entra_app, graph):
    app = entra_app()
    client, token = _admin(app)
    # Lo que diga el formulario aparte del identificador no cuenta: se vuelve a leer del directorio
    client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-pedro",
                                             "username": "otro-nombre", "role": "admin"})
    with app.app_context():
        pedro = users.get_by_external(get_db(), "entra", "oid-pedro")
    assert pedro["username"] == "pedro@contoso.com" and pedro["role"] == "user"
    page = client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "no-existe"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No se encontró a esa persona" in page


def test_not_in_the_allowed_groups(entra_app, graph):
    app = entra_app(allowed_groups=["99999999-9999-9999-9999-999999999999"])
    client, token = _admin(app)
    page = client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-juan"},
                       follow_redirects=True).get_data(as_text=True)
    assert "no está en los grupos que pueden entrar" in page                # no podría entrar: no se importa


def test_name_conflicts_and_linking(entra_app, graph):
    app = entra_app()
    client, token = _admin(app)
    add_user(app, "pedro@contoso.com")                                       # una local con el mismo nombre
    assert "el nombre ya existe" in client.get("/admin/users/import?source=entra&q=pe").get_data(as_text=True)
    page = client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-pedro"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Ya hay una cuenta llamada" in page
    add_user(app, "juan@contoso.com", source="entra")                        # dada de alta a mano, sin identificador
    client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-juan"})
    with app.app_context():
        assert users.get_by_external(get_db(), "entra", "oid-juan")["username"] == "juan@contoso.com"
    assert last_audit(app, "user_imported")["detail"].endswith(" linked")


def test_strip_domain_and_unreadable_directory(entra_app, graph, monkeypatch):
    app = entra_app(strip_domain=True)
    client, token = _admin(app)
    client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-juan"})
    with app.app_context():
        assert users.get_by_external(get_db(), "entra", "oid-juan")["username"] == "juan"
    monkeypatch.setattr(entra_directory, "search_users", lambda ecfg, text, limit=25: None)
    assert "No se pudo leer el directorio" in client.get("/admin/users/import?q=ju").get_data(as_text=True)


def test_not_available_without_entra(make_app):
    app = make_app()
    client, _token = _admin(app)
    assert "Importar de" not in client.get("/admin/users").get_data(as_text=True)
    assert client.get("/admin/users/import").status_code == 302


def test_import_several_at_once(entra_app, graph):
    app = entra_app()
    client, token = _admin(app)
    page = client.get("/admin/users/import?source=entra&q=ju").get_data(as_text=True)
    assert 'form="import-bulk"' in page and 'id="import-bulk"' in page and "Importar las seleccionadas" in page
    resp = client.post("/admin/users/import", data={"_csrf": token, "source": "entra",
                                                    "ids": ["oid-juan", "oid-pedro", "oid-juan", "no-existe"]},
                       follow_redirects=True).get_data(as_text=True)
    assert "2 personas importadas" in resp and "No se encontró a esa persona" in resp
    with app.app_context():
        assert {u["username"] for u in users.list_all(get_db()) if u["source"] == "entra"} == {
            "juan@contoso.com", "pedro@contoso.com"}
    nothing = client.post("/admin/users/import", data={"_csrf": token, "source": "entra"}, follow_redirects=True)
    assert "Selecciona al menos una persona" in nothing.get_data(as_text=True)


def test_show_all_page_by_page(entra_app, graph):
    app = entra_app()
    client, _token = _admin(app)
    first = client.get("/admin/users/import?source=entra&all=1").get_data(as_text=True)
    assert "Juan Pérez" in first and "Pedro" not in first and 'id="import-more"' in first   # la primera página
    more = client.get("/admin/users/import?source=entra&all=1&cursor=1&rows=1")
    assert "Pedro Ruiz" in more.get_data(as_text=True) and "<table" not in more.get_data(as_text=True)
    assert more.headers["X-Next"] == ""                                                  # era la última


def test_people_not_assigned_to_the_application(entra_app, graph):
    app = entra_app()
    client, token = _admin(app)
    graph.assignment = {"required": True, "users": {"oid-pedro"}}         # solo Pedro (o un grupo suyo)
    page = client.get("/admin/users/import?source=entra&all=1").get_data(as_text=True)
    assert "no podrá entrar" in page and "Asignación requerida" in page
    resp = client.post("/admin/users/import", data={"_csrf": token, "source": "entra", "external_id": "oid-juan"},
                       follow_redirects=True).get_data(as_text=True)
    assert "importada" in resp and "Sin asignar a la aplicación" in resp                # se importa, con el aviso
    graph.assignment = None                                                              # sin permiso para leerlo
    page = client.get("/admin/users/import?source=entra&q=pe").get_data(as_text=True)
    assert "Application.Read.All" in page

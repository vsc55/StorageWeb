"""Administración de grupos: vistas Lista (A), Paneles (B) y Matriz (C)."""
import pytest

from storageweb.core import groups as gc
from storageweb.core.storage import available_roots
from storageweb.db.repositories import audit, users
from storageweb.db.repositories import groups as repo
from storageweb.web.context import get_db, settings
from tests.helpers import add_user, page_form, visible


@pytest.fixture
def app(make_app, tmp_path):
    return make_app({"storage": {"create_shares": True, "shares": [
        {"name": "software", "label": "Software", "path": str(tmp_path / "sw"), "users": [], "groups": []},
        {"name": "publico", "label": "Público", "path": str(tmp_path / "pub"), "users": ["*"]},
        {"name": "facturas", "label": "Facturas", "path": str(tmp_path / "fac"), "users": [], "groups": [],
         "read_only": True}]}})


def _group(app, name="it", **kw):
    with app.app_context():
        return gc.create_group(get_db(), name=name, **kw)


def _get(app, gid):
    with app.app_context():
        return repo.get_by_id(get_db(), gid)


def _actions(app):
    with app.app_context():
        return [r["action"] for r in audit.recent(get_db(), 20)]


@pytest.mark.parametrize("url", ["/admin/groups/", "/admin/groups/list", "/admin/groups/panel",
                                 "/admin/groups/matrix", "/admin/groups/new"])
def test_admin_only(logged, url):
    client, _ = logged
    assert client.get(url).status_code == 403


def test_rail_link_and_last_view(admin):
    client, _ = admin
    assert client.get("/admin/groups/").location.endswith("/admin/groups/list")
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert 'href="/admin/groups/"' in html
    client.get("/admin/groups/panel")
    assert client.get("/admin/groups/").location.endswith("/admin/groups/panel")
    # La matriz es de Acceso: visitarla no cambia a dónde lleva Personas → Grupos
    client.get("/admin/groups/matrix")
    assert client.get("/admin/groups/").location.endswith("/admin/groups/panel")


# --------------------------------------------------------------------------- A: lista + ficha

def test_create_edit_delete_group(app, admin):
    client, token = admin
    resp = client.post("/admin/groups/new", data={"_csrf": token, "name": "RRHH", "label": "Recursos Humanos",
                                                  "description": "Personal", "source": "local"})
    with app.app_context():
        group = repo.get_by_name(get_db(), "rrhh")
    assert resp.location.endswith(f"/admin/groups/{group['id']}") and group["name"] == "rrhh"
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Recursos Humanos" in html and "Personal" in html

    resp = client.post(f"/admin/groups/{group['id']}", data={
        "_csrf": token, "label": "RR. HH.", "description": "", "source": "local", "external_id": ""})
    assert resp.status_code == 302 and _get(app, group["id"])["label"] == "RR. HH."

    html = client.post("/admin/groups/new", data={"_csrf": token, "name": "rrhh", "label": "x", "source": "local"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Ya existe un grupo" in html

    client.post(f"/admin/groups/{group['id']}/delete", data={"_csrf": token})
    assert _get(app, group["id"]) is None
    assert {"group_created", "group_updated", "group_deleted"} <= set(_actions(app))


def test_members_manual_and_sync(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas", source="entra", external_id="oid-it")
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.sync_external(get_db(), eva, "entra", ["oid-it"])
    ana = add_user(app, "ana")

    client.post(f"/admin/groups/{gid}/members", data={"_csrf": token, "username": "ana"})
    html = client.get(f"/admin/groups/{gid}").get_data(as_text=True)
    assert "Sincronizado" in html and "Manual" in html and "Se gestiona en Entra ID" in html

    html = client.post(f"/admin/groups/{gid}/members/{eva}/remove", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "se cambia allí" in html
    client.post(f"/admin/groups/{gid}/members/{ana}/remove", data={"_csrf": token})
    with app.app_context():
        assert repo.get_membership(get_db(), ana, gid) is None
    html = client.post(f"/admin/groups/{gid}/members", data={"_csrf": token, "username": "nadie"},
                       follow_redirects=True).get_data(as_text=True)
    assert "no existe" in html
    assert {"group_member_added", "group_member_removed"} <= set(_actions(app))


def test_detected_groups_can_be_registered(app, admin):
    client, _ = admin
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.sync_external(get_db(), eva, "entra", ["9b1d07aa"])
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Grupos sin dar de alta (1)" in html and "9b1d07aa" in html
    html = client.get("/admin/groups/new?source=entra&external_id=9b1d07aa").get_data(as_text=True)
    assert 'value="9b1d07aa"' in html and 'value="entra" checked' in html


# --------------------------------------------------------------------------- B: paneles

def test_panel_view_tabs(app, admin):
    client, token = admin
    first = _group(app, "aaa", label="Alfa")
    second = _group(app, "bbb", label="Beta")
    html = client.get("/admin/groups/panel").get_data(as_text=True)
    assert '<h2 class="md-title">Administradores</h2>' in html          # el grupo de serie va primero
    html = client.get(f"/admin/groups/panel?g={first}").get_data(as_text=True)
    assert '<h2 class="md-title">Alfa</h2>' in html
    html = client.get(f"/admin/groups/panel?g={second}&tab=link").get_data(as_text=True)
    assert '<h2 class="md-title">Beta</h2>' in html and 'name="external_id"' in html
    resp = client.post(f"/admin/groups/{second}", data={
        "_csrf": token, "label": "Beta 2", "description": "", "source": "local", "external_id": "",
        "next": f"/admin/groups/panel?g={second}&tab=link"})
    assert resp.location.endswith(f"/admin/groups/panel?g={second}&tab=link")
    html = client.get(f"/admin/groups/panel?g={first}&tab=shares").get_data(as_text=True)
    assert "no da acceso a ninguna carpeta" in html


# --------------------------------------------------------------------------- C: matriz

def test_matrix_changes_share_access(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas")
    uid = add_user(app, "luis")
    with app.app_context():
        gc.set_manual_groups(get_db(), uid, ["it"])

    html = client.get("/admin/groups/matrix").get_data(as_text=True)
    assert f'name="access-{gid}-software"' in html
    assert f'name="access-{gid}-publico"' not in html and "Todos" in html   # abierta a todos

    def roots():
        with app.test_request_context():
            return {r["name"]: r["read_only"] for r in available_roots(users.get_by_id(get_db(), uid), settings())}
    assert "software" not in roots()

    resp = client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{gid}-software": "write",
                                                     f"access-{gid}-facturas": "write"})
    assert resp.status_code == 302
    assert roots()["software"] is False and roots()["facturas"] is True      # carpeta de solo lectura
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{gid}-software": "read",
                                              f"access-{gid}-facturas": "read"})
    assert roots()["software"] is True
    html = client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{gid}-software": "read"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No había cambios" in html
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{gid}-software": "none"})
    assert "software" not in roots()
    assert "group_access_updated" in _actions(app)


def test_settings_page_keeps_read_only_groups(app, admin):
    client, token = admin
    gid = _group(app, "it")
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{gid}-software": "read"})
    # La ficha de la carpeta lo muestra y guardarla sin cambios lo conserva
    data = page_form(client, "/admin/access/folders/software")
    assert data["entry_ref"] == ["it"] and data["entry_level"] == ["read"]
    assert client.post("/admin/access/folders/software", data=data).status_code == 302
    with app.test_request_context():
        assert settings()["storage"]["shares"][0]["read_only_groups"] == ["it"]


# --------------------------------------------------------------------------- ficha de usuario

def test_user_form_group_chips(app, admin):
    client, token = admin
    gid = _group(app, "fin", label="Finanzas")
    entra = _group(app, "it", label="Sistemas", source="entra", external_id="oid-it")
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.sync_external(get_db(), eva, "entra", ["oid-it", "oid-raro"])
    html = visible(client.get(f"/admin/users/{eva}").get_data(as_text=True))
    assert "chip-sync" in html and "Sistemas" in html and "oid-raro" in html and "sin dar de alta" in html
    assert f'<option value="{gid}">Finanzas (fin)</option>' in html and f'value="{entra}"' not in html

    client.post(f"/admin/users/{eva}/groups", data={"_csrf": token, "group_id": gid})
    with app.app_context():
        assert gc.split(users.get_by_id(get_db(), eva)["groups"]) == {"oid-it", "oid-raro", "it", "fin"}
    html = client.get(f"/admin/users/{eva}").get_data(as_text=True)
    assert "Quitar del grupo Finanzas" in html


def test_new_user_groups_create_local_groups(app, admin):
    client, token = admin
    client.post("/admin/users/new", data={"_csrf": token, "username": "nuevo", "source": "local",
                                          "password": "contraseña-larga", "role": "user", "groups": "Ventas",
                                          "enabled": "on"})
    with app.app_context():
        assert repo.get_by_name(get_db(), "ventas")["source"] == "local"
        assert users.get_by_username(get_db(), "nuevo")["groups"] == "ventas"


def test_sso_login_keeps_manual_groups(entra_app, token_endpoint):
    """Un grupo puesto a mano a un usuario de Entra ID ya no se pierde al volver a iniciar sesión."""
    from tests.sso_helpers import finish_login, start_login

    app = entra_app()
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    with app.app_context():
        user = users.get_by_username(get_db(), "juan@contoso.com")
        gc.set_manual_groups(get_db(), user["id"], ["finanzas"])
    other = app.test_client()
    _, q = start_login(other, token_endpoint)
    finish_login(other, q["state"])
    with app.app_context():
        assert "finanzas" in users.get_by_username(get_db(), "juan@contoso.com")["groups"]


def test_builtin_admins_group_pages(app, admin):
    client, token = admin
    with app.app_context():
        admins = repo.get_builtin(get_db(), gc.ADMINS_GROUP)
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Administradores" in html
    html = client.get(f"/admin/groups/{admins['id']}").get_data(as_text=True)
    assert "Grupo de serie" in html and "Eliminar grupo" not in html and 'name="label"' not in html
    assert "Rol de administrador" in html and "root" in html

    html = client.post(f"/admin/groups/{admins['id']}/delete", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "no se puede eliminar" in html
    client.post(f"/admin/groups/{admins['id']}", data={"_csrf": token, "label": "Otro", "source": "local"})
    with app.app_context():
        assert repo.get_builtin(get_db(), gc.ADMINS_GROUP)["label"] == "Administrators"

    ana = add_user(app, "ana")
    client.post(f"/admin/groups/{admins['id']}/members", data={"_csrf": token, "username": "ana"})
    with app.app_context():
        assert users.get_by_id(get_db(), ana)["role"] == "admin"
    client.post(f"/admin/groups/{admins['id']}/members/{ana}/remove", data={"_csrf": token})
    with app.app_context():
        assert users.get_by_id(get_db(), ana)["role"] == "user"
    html = client.get(f"/admin/groups/panel?g={admins['id']}&tab=link").get_data(as_text=True)
    assert "no se puede editar" in html and 'name="external_id"' not in html


# --------------------------------------------------------------------------- alta desde el directorio (Entra ID)

G_SALES, G_IT = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
DIRECTORY = {G_SALES: {"name": "Ventas España", "description": "Equipo comercial"},
             G_IT: {"name": "Permitir Instalación", "description": ""}}


@pytest.fixture
def directory(monkeypatch):
    from storageweb.providers.entra import directory as entra_directory
    monkeypatch.setattr(entra_directory, "info_for",
                        lambda ecfg, ids: {i: DIRECTORY[i] for i in ids if i in DIRECTORY})
    monkeypatch.setattr(entra_directory, "names_for",
                        lambda ecfg, ids: {i: DIRECTORY[i]["name"] for i in ids if i in DIRECTORY})


def test_suggest_name(app):
    with app.app_context():
        assert gc.suggest_name(get_db(), "Permitir Instalación") == "permitir-instalacion"
        assert gc.suggest_name(get_db(), "Test - jpastor") == "test-jpastor"
        assert gc.suggest_name(get_db(), "Grp_o365") == "grp_o365"
        assert gc.suggest_name(get_db(), "", "  ", "StorageWeb.Admin") == "storageweb.admin"
        assert gc.suggest_name(get_db(), "¿¡!?") == "group"
        gc.create_group(get_db(), name="ventas", label="Ventas")
        assert gc.suggest_name(get_db(), "Ventas") == "ventas-2"


def test_register_form_is_filled_from_the_directory(app, admin, directory):
    client, token = admin
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.sync_external(get_db(), eva, "entra", [G_SALES])
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert f"/admin/groups/new?source=entra&amp;external_id={G_SALES}" in html and "<strong>Ventas España</strong>" in html
    html = client.get(f"/admin/groups/new?source=entra&external_id={G_SALES}").get_data(as_text=True)
    assert 'name="name" value="ventas-espana"' in html and 'value="Ventas España"' in html
    assert 'value="Equipo comercial"' in html
    # Sin identificador en el envío se propone igual
    client.post("/admin/groups/new", data={"_csrf": token, "name": "", "label": "", "description": "",
                                           "source": "entra", "external_id": G_SALES})
    with app.app_context():
        group = repo.get_by_external(get_db(), "entra", G_SALES)
    assert group["name"] == "ventas-espana" and group["label"] == "Ventas España"


def test_register_all_detected(app, admin, directory):
    client, token = admin
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.create_group(get_db(), name="permitir-instalacion", label="Otro")   # el nombre ya está cogido
        gc.sync_external(get_db(), eva, "entra", [G_SALES, G_IT, "storageweb.admin"])
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Dar de alta todos (3)" in html
    resp = client.post("/admin/groups/register-detected", data={"_csrf": token, "next": "/admin/groups/list"})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/admin/groups/list")
    with app.app_context():
        sales = repo.get_by_external(get_db(), "entra", G_SALES)
        it = repo.get_by_external(get_db(), "entra", G_IT)
        role = repo.get_by_external(get_db(), "entra", "storageweb.admin")
        groups_of_eva = users.get_by_id(get_db(), eva)["groups"]
    assert (sales["name"], sales["label"], sales["description"]) == ("ventas-espana", "Ventas España", "Equipo comercial")
    assert (it["name"], it["label"]) == ("permitir-instalacion-2", "Permitir Instalación")
    assert (role["name"], role["label"]) == ("storageweb.admin", "storageweb.admin")   # App Role: sin directorio
    assert "ventas-espana" in groups_of_eva                                             # miembro sincronizado ya
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Grupos sin dar de alta" not in html
    assert _actions(app).count("group_created") >= 3

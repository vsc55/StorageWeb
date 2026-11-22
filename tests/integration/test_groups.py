"""Administración de grupos: vistas Lista (A), Paneles (B) y Matriz (C)."""
import pytest

from storageweb.core import groups as gc
from storageweb.core.storage import available_roots
from storageweb.db.repositories import users
from storageweb.db.repositories import groups as repo
from storageweb.web.context import get_db, settings
from tests.helpers import add_user, page_form, visible, U, G, audit_actions, last_audit, signed_in


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
    assert resp.location.endswith(f"/admin/groups/{G(group['id'])}") and group["name"] == "rrhh"
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Recursos Humanos" in html and "Personal" in html

    resp = client.post(f"/admin/groups/{G(group['id'])}", data={
        "_csrf": token, "label": "RR. HH.", "description": "", "source": "local", "external_id": ""})
    assert resp.status_code == 302 and _get(app, group["id"])["label"] == "RR. HH."

    html = client.post("/admin/groups/new", data={"_csrf": token, "name": "rrhh", "label": "x", "source": "local"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Ya existe un grupo" in html

    client.post(f"/admin/groups/{G(group['id'])}/delete", data={"_csrf": token})
    assert _get(app, group["id"]) is None
    assert {"group_created", "group_updated", "group_deleted"} <= set(audit_actions(app))


def test_members_manual_and_sync(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas", source="entra", external_id="oid-it")
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.sync_external(get_db(), eva, "entra", ["oid-it"])
    ana = add_user(app, "ana")

    client.post(f"/admin/groups/{G(gid)}/members", data={"_csrf": token, "username": "ana"})
    html = client.get(f"/admin/groups/{G(gid)}").get_data(as_text=True)
    assert "Sincronizado" in html and "Manual" in html and "Se gestiona en Entra ID" in html

    html = client.post(f"/admin/groups/{G(gid)}/members/{U(eva)}/remove", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "se cambia allí" in html
    client.post(f"/admin/groups/{G(gid)}/members/{U(ana)}/remove", data={"_csrf": token})
    with app.app_context():
        assert repo.get_membership(get_db(), ana, gid) is None
    html = client.post(f"/admin/groups/{G(gid)}/members", data={"_csrf": token, "username": "nadie"},
                       follow_redirects=True).get_data(as_text=True)
    assert "no existe" in html
    assert {"group_member_added", "group_member_removed"} <= set(audit_actions(app))


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
    html = client.get(f"/admin/groups/panel?g={G(first)}").get_data(as_text=True)
    assert '<h2 class="md-title">Alfa</h2>' in html
    html = client.get(f"/admin/groups/panel?g={G(second)}&tab=link").get_data(as_text=True)
    assert '<h2 class="md-title">Beta</h2>' in html and 'name="external_id"' in html
    resp = client.post(f"/admin/groups/{G(second)}", data={
        "_csrf": token, "label": "Beta 2", "description": "", "source": "local", "external_id": "",
        "next": f"/admin/groups/panel?g={G(second)}&tab=link"})
    assert resp.location.endswith(f"/admin/groups/panel?g={G(second)}&tab=link")
    html = client.get(f"/admin/groups/panel?g={G(first)}&tab=shares").get_data(as_text=True)
    assert "no da acceso a ninguna carpeta" in html


# --------------------------------------------------------------------------- C: matriz

def test_matrix_changes_share_access(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas")
    uid = add_user(app, "luis")
    with app.app_context():
        gc.set_manual_groups(get_db(), uid, ["it"])

    html = client.get("/admin/groups/matrix").get_data(as_text=True)
    assert f'name="access-{G(gid)}-software"' in html
    assert f'name="access-{G(gid)}-publico"' not in html and "Todos" in html   # abierta a todos

    def roots():
        with app.test_request_context():
            return {r["name"]: r["read_only"] for r in available_roots(users.get_by_id(get_db(), uid), settings())}
    assert "software" not in roots()

    resp = client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{G(gid)}-software": "write",
                                                     f"access-{G(gid)}-facturas": "write"})
    assert resp.status_code == 302
    assert roots()["software"] is False and roots()["facturas"] is True      # carpeta de solo lectura
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{G(gid)}-software": "read",
                                              f"access-{G(gid)}-facturas": "read"})
    assert roots()["software"] is True
    html = client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{G(gid)}-software": "read"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No había cambios" in html
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{G(gid)}-software": "none"})
    assert "software" not in roots()
    assert "group_access_updated" in audit_actions(app)


def test_settings_page_keeps_read_only_groups(app, admin):
    client, token = admin
    gid = _group(app, "it")
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{G(gid)}-software": "read"})
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
    html = visible(client.get(f"/admin/users/{U(eva)}").get_data(as_text=True))
    assert "chip-sync" in html and "Sistemas" in html and "oid-raro" in html and "sin dar de alta" in html
    assert f'<option value="{G(gid)}">Finanzas (fin)</option>' in html and f'value="{G(entra)}"' not in html

    client.post(f"/admin/users/{U(eva)}/groups", data={"_csrf": token, "group_uid": G(gid)})
    with app.app_context():
        assert gc.split(users.get_by_id(get_db(), eva)["groups"]) == {"oid-it", "oid-raro", "it", "fin"}
    html = client.get(f"/admin/users/{U(eva)}").get_data(as_text=True)
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
    from tests.sso_helpers import sso_login

    app = entra_app()
    client = app.test_client()
    sso_login(client, token_endpoint)
    with app.app_context():
        user = users.get_by_username(get_db(), "juan@contoso.com")
        gc.set_manual_groups(get_db(), user["id"], ["finanzas"])
    other = app.test_client()
    sso_login(other, token_endpoint)
    with app.app_context():
        assert "finanzas" in users.get_by_username(get_db(), "juan@contoso.com")["groups"]


def test_builtin_admins_group_pages(app, admin):
    client, token = admin
    with app.app_context():
        admins = repo.get_builtin(get_db(), gc.ADMINS_GROUP)
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "Administradores" in html
    html = client.get(f"/admin/groups/{G(admins['id'])}").get_data(as_text=True)
    assert "Grupo de serie" in html and "Eliminar grupo" not in html and 'name="label"' not in html
    assert "Rol de administrador" in html and "root" in html

    html = client.post(f"/admin/groups/{G(admins['id'])}/delete", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "no se puede eliminar" in html
    client.post(f"/admin/groups/{G(admins['id'])}", data={"_csrf": token, "label": "Otro", "source": "local"})
    with app.app_context():
        assert repo.get_builtin(get_db(), gc.ADMINS_GROUP)["label"] == "Administrators"

    ana = add_user(app, "ana")
    client.post(f"/admin/groups/{G(admins['id'])}/members", data={"_csrf": token, "username": "ana"})
    with app.app_context():
        assert users.get_by_id(get_db(), ana)["role"] == "admin"
    client.post(f"/admin/groups/{G(admins['id'])}/members/{U(ana)}/remove", data={"_csrf": token})
    with app.app_context():
        assert users.get_by_id(get_db(), ana)["role"] == "user"
    html = client.get(f"/admin/groups/panel?g={G(admins['id'])}&tab=link").get_data(as_text=True)
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
    assert audit_actions(app).count("group_created") >= 3


# --------------------------------------------------------------------------- desactivar, clonar e importar

def _roots(app, uid):
    with app.app_context():
        return {r["name"] for r in available_roots(users.get_by_id(get_db(), uid), settings())}


def _with_access(client, token, gid, share="software", level="write"):
    client.post("/admin/groups/matrix", data={"_csrf": token, f"access-{G(gid)}-{share}": level})


def _builtin(app):
    with app.app_context():
        return repo.get_builtin(get_db(), "admins")


def _editors_role(app, gid):
    from storageweb.core import roles
    with app.app_context():
        role = roles.create(get_db(), "Editores", permissions=["edit"])
        gc.set_role(get_db(), _get(app, gid), role)
    return role


def test_a_disabled_group_gives_nothing_until_enabled(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas")
    ana = add_user(app, "ana")
    with app.app_context():
        gc.add_member(get_db(), _get(app, gid), users.get_by_id(get_db(), ana))
    role = _editors_role(app, gid)
    _with_access(client, token, gid)
    assert "software" in _roots(app, ana)
    resp = client.post(f"/admin/groups/{G(gid)}/status", data={"_csrf": token, "enabled": "0"})
    assert resp.status_code == 302
    with app.app_context():
        assert "it" not in users.groups_of(users.get_by_id(get_db(), ana)) and not _get(app, gid)["enabled"]
    assert "software" not in _roots(app, ana)                         # ni su carpeta…
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert 'class="row-disabled"' in html and "avatar-ban" in html
    assert "Sistemas" in client.get("/admin/groups/list?status=disabled").get_data(as_text=True)
    assert "Sistemas" not in visible(client.get("/admin/groups/list?status=active").get_data(as_text=True))
    # …pero se conserva entero: miembros, rol y acceso
    with app.app_context():
        assert [m["username"] for m in gc.members(get_db(), _get(app, gid))] == ["ana"]
        assert _get(app, gid)["role"] == role
    client.post(f"/admin/groups/{G(gid)}/status", data={"_csrf": token, "enabled": "1"})
    assert "software" in _roots(app, ana)
    assert audit_actions(app)[:2] == ["group_enabled", "group_disabled"]
    admins = _builtin(app)
    client.post(f"/admin/groups/{G(admins['id'])}/status", data={"_csrf": token, "enabled": "0"})
    assert _builtin(app)["enabled"]                                   # el de serie, nunca


def test_the_provider_cannot_bring_back_a_disabled_group(app):
    gid = _group(app, "it", label="Sistemas", source="entra", external_id="oid-it")
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    with app.app_context():
        gc.set_enabled(get_db(), _get(app, gid), False)
        gc.sync_external(get_db(), eva, "entra", ["oid-it", "oid-otro"])
        assert users.groups_of(users.get_by_id(get_db(), eva)) == {"oid-otro"}   # ni el nombre ni el Object ID
        gc.set_enabled(get_db(), _get(app, gid), True)
        assert users.groups_of(users.get_by_id(get_db(), eva)) == {"oid-it", "oid-otro", "it"}


def test_clone_with_members_role_and_access(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas", source="entra", external_id="oid-it", description="Soporte")
    eva = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    ana = add_user(app, "ana")
    with app.app_context():
        gc.sync_external(get_db(), eva, "entra", ["oid-it"])            # sincronizada
        gc.add_member(get_db(), _get(app, gid), users.get_by_id(get_db(), ana))
    role = _editors_role(app, gid)
    _with_access(client, token, gid, level="read")
    page = client.get(f"/admin/groups/new?copy={G(gid)}").get_data(as_text=True)
    assert "Clonar «Sistemas»" in page and 'value="Sistemas (copia)"' in page and 'value="Soporte"' in page
    assert "Sus miembros (2)" in page and "Su acceso a 1 carpeta compartida" in page
    assert 'name="source" value="local"' in page and 'name="external_id"' not in page
    resp = client.post("/admin/groups/new", data={
        "_csrf": token, "copy": G(gid), "name": "it-copia", "label": "Sistemas (copia)", "description": "Soporte",
        "source": "entra", "role": role, "home_quota_mb": "", "copy_members": "1", "copy_access": "1"})
    assert resp.status_code == 302
    with app.app_context():
        clone = repo.get_by_name(get_db(), "it-copia")
        members = {m["username"]: m["origin"] for m in repo.members(get_db(), clone["id"])}
        software = next(s for s in settings()["storage"]["shares"] if s["name"] == "software")
    assert clone["source"] == "local" and clone["role"] == role       # siempre local, aunque se mande otro
    assert members == {"ana": "manual", "eva@x.com": "manual"}
    assert gc.share_level(clone, software) == "read"
    assert "copy=it" in last_audit(app, "group_created")["detail"]
    # Sin las casillas: solo los datos
    client.post("/admin/groups/new", data={"_csrf": token, "copy": G(gid), "name": "it-vacio", "label": "Vacío",
                                           "source": "local"})
    with app.app_context():
        empty = repo.get_by_name(get_db(), "it-vacio")
        software = next(s for s in settings()["storage"]["shares"] if s["name"] == "software")
        assert not repo.members(get_db(), empty["id"])
    assert gc.share_level(empty, software) == "none"
    # Clonar la copia propone «(copia 2)», no «(copia) (copia)»
    assert 'value="Sistemas (copia 2)"' in client.get(f"/admin/groups/new?copy={G(clone['id'])}").get_data(as_text=True)


def test_clone_from_the_panels_goes_to_the_new_group(app, admin):
    client, token = admin
    gid = _group(app, "it", label="Sistemas")
    page = client.get(f"/admin/groups/panel?g={G(gid)}").get_data(as_text=True)
    assert f"/admin/groups/new?copy={G(gid)}" in page and "Desactivar" in page
    resp = client.post("/admin/groups/new", data={"_csrf": token, "copy": G(gid), "name": "it2", "label": "Otro",
                                                  "source": "local", "next": f"/admin/groups/panel?g={G(gid)}"})
    with app.app_context():
        new = repo.get_by_name(get_db(), "it2")
    assert resp.location.endswith(f"/admin/groups/panel?g={new['uid']}")


def test_group_avatar_with_initials(app, admin):
    client, _ = admin
    _group(app, "rrhh", label="Recursos humanos")
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert 'class="avatar group-avatar" aria-hidden="true">RH</span>' in html
    assert ">RH</span>" in client.get("/admin/groups/panel").get_data(as_text=True)


@pytest.fixture
def groups_directory(monkeypatch):
    from storageweb.providers.entra import directory as entra_directory
    everyone = sorted(({"id": k, **v} for k, v in DIRECTORY.items()), key=lambda g: g["name"])
    monkeypatch.setattr(entra_directory, "configured", lambda ecfg: True)
    monkeypatch.setattr(entra_directory, "info_for",
                        lambda ecfg, ids: {i: DIRECTORY[i] for i in ids if i in DIRECTORY})
    monkeypatch.setattr(entra_directory, "search_groups", lambda ecfg, text, limit=20: [
        g for g in everyone if g["name"].lower().startswith(text.lower())])

    def pages(ecfg, skiptoken="", page_size=50):
        start = int(skiptoken or 0)
        return everyone[start:start + 1], (str(start + 1) if start + 1 < len(everyone) else "")
    monkeypatch.setattr(entra_directory, "list_groups", pages)


def test_import_groups_from_entra(entra_app, groups_directory):
    app = entra_app()
    client, token = signed_in(app, "root", role="admin", csrf_url="/admin/groups/list")
    assert "/admin/groups/import?source=entra" in client.get("/admin/groups/list").get_data(as_text=True)
    page = client.get("/admin/groups/import?source=entra&q=ven").get_data(as_text=True)
    assert "Ventas España" in page and "Permitir Instalación" not in page and "directory-import.js" in page
    assert "Permitir" in client.get("/admin/groups/import?source=entra&q=per&partial=1").get_data(as_text=True)
    # Todos, por páginas (uno por página aquí): la siguiente se pide sola con ?rows=1
    page = client.get("/admin/groups/import?source=entra&all=1").get_data(as_text=True)
    assert "Permitir Instalación" in page and 'id="import-more"' in page
    rows = client.get("/admin/groups/import?source=entra&all=1&cursor=1&rows=1")
    assert "Ventas España" in rows.get_data(as_text=True) and rows.headers["X-Next"] == ""
    # Uno, y luego varios (el ya importado no se duplica)
    client.post("/admin/groups/import", data={"_csrf": token, "source": "entra", "external_id": G_SALES})
    with app.app_context():
        sales = repo.get_by_external(get_db(), "entra", G_SALES)
    assert (sales["name"], sales["label"], sales["description"]) == ("ventas-espana", "Ventas España", "Equipo comercial")
    assert "ya dado de alta" in client.get("/admin/groups/import?source=entra&q=ven").get_data(as_text=True)
    client.post("/admin/groups/import", data={"_csrf": token, "source": "entra", "ids": [G_SALES, G_IT, "no-existe"]})
    with app.app_context():
        assert repo.get_by_external(get_db(), "entra", G_IT)["name"] == "permitir-instalacion"
        assert len([g for g in repo.list_all(get_db()) if g["source"] == "entra"]) == 2
    assert last_audit(app, "group_created")["detail"].endswith(" import")


def test_import_groups_needs_the_directory(app, admin):
    client, _ = admin
    resp = client.get("/admin/groups/import")
    assert resp.status_code == 302 and resp.location.endswith("/admin/groups/")
    assert "/admin/groups/import" not in client.get("/admin/groups/list").get_data(as_text=True)


def test_clone_the_builtin_group(app, admin):
    """El de serie también se clona: la copia es local, con quienes tienen el rol Administrador como miembros a mano
    (no les da ese rol) y su acceso a carpetas; no se desactiva."""
    client, token = admin
    admins = _builtin(app)
    _with_access(client, token, admins["id"], level="read")
    page = client.get(f"/admin/groups/panel?g={admins['uid']}").get_data(as_text=True)
    assert f"/admin/groups/new?copy={admins['uid']}" in page and "Desactivar" not in page
    page = client.get(f"/admin/groups/new?copy={admins['uid']}").get_data(as_text=True)
    assert "Sus miembros (1)" in page or "Su miembro (1)" in page
    client.post("/admin/groups/new", data={"_csrf": token, "copy": admins["uid"], "name": "jefes", "label": "Jefes",
                                           "source": "local", "copy_members": "1", "copy_access": "1"})
    with app.app_context():
        clone = repo.get_by_name(get_db(), "jefes")
        software = next(s for s in settings()["storage"]["shares"] if s["name"] == "software")
        assert [m["origin"] for m in repo.members(get_db(), clone["id"])] == ["manual"]
    assert not clone["builtin"] and clone["source"] == "local" and clone["role"] is None
    assert gc.share_level(clone, software) == "read"

def test_a_disabled_group_gives_no_permissions_or_quota(app, admin):
    """Lo que da un grupo (rol con sus permisos, cuota de la carpeta personal) desaparece al desactivarlo y vuelve al
    activarlo, sin volver a entrar: todo se calcula con la lista efectiva de grupos de la persona."""
    from storageweb.core.permissions import permissions_for
    from storageweb.core.storage import home_quota_mb
    from storageweb.db.repositories import catalog
    client, token = admin
    gid = _group(app, "it", label="Sistemas")
    ana = add_user(app, "ana")
    _editors_role(app, gid)
    with app.app_context():
        gc.add_member(get_db(), _get(app, gid), users.get_by_id(get_db(), ana))
        catalog.set_group_quota(get_db(), "it", 50)
        catalog.bump_all(get_db(), None)
        get_db().commit()

    def gives():
        with app.app_context():
            user = users.get_by_id(get_db(), ana)
            return "edit" in permissions_for(user, settings()), home_quota_mb(user, settings())
    assert gives() == (True, 50)
    client.post(f"/admin/groups/{G(gid)}/status", data={"_csrf": token, "enabled": "0"})
    assert gives() == (False, 0)
    # La persona lo ve marcado en su ficha y en la lista (sigue siendo miembro)
    page = client.get(f"/admin/users/{U(ana)}").get_data(as_text=True)
    assert 'class="chip is-off"' in page and "Grupo desactivado: no da nada" in page
    assert 'class="group-tag is-off"' in client.get("/admin/users").get_data(as_text=True)
    client.post(f"/admin/groups/{G(gid)}/status", data={"_csrf": token, "enabled": "1"})
    assert gives() == (True, 50)

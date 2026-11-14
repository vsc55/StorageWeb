"""Administración de usuarios: vistas Lista (A) y Paneles (B) y acciones en bloque."""
import pytest

from storageweb.core import groups as gc
from storageweb.db.repositories import audit, users
from storageweb.web.context import get_db
from tests.helpers import add_user, login, visible


@pytest.fixture
def app(make_app, tmp_path):
    return make_app({"storage": {"create_shares": True, "shares": [
        {"name": "software", "label": "Software", "path": str(tmp_path / "sw"), "users": [], "groups": ["it"]},
        {"name": "publico", "label": "Público", "path": str(tmp_path / "pub"), "users": ["*"]}]}})


def _user(app, name):
    with app.app_context():
        return users.get_by_username(get_db(), name)


def _group(app, name, label):
    with app.app_context():
        return gc.create_group(get_db(), name=name, label=label)


def _join(app, uid, *names):
    with app.app_context():
        gc.set_manual_groups(get_db(), uid, list(names))


@pytest.mark.parametrize("url", ["/admin/users/", "/admin/users/panel"])
def test_admin_only(logged, url):
    client, _ = logged
    assert client.get(url).status_code == 403


def test_index_remembers_last_view(admin):
    client, _ = admin
    assert client.get("/admin/users/").location.endswith("/admin/users")
    client.get("/admin/users/panel")
    assert client.get("/admin/users/").location.endswith("/admin/users/panel")


# --------------------------------------------------------------------------- A: lista

def test_list_filters_and_counts(app, admin):
    client, _ = admin
    gid = _group(app, "it", "Sistemas")
    ana = add_user(app, "ana")
    _join(app, ana, "it")
    add_user(app, "eva@x.com", password=None, source="entra")
    add_user(app, "baja", enabled=False)

    html = client.get("/admin/users").get_data(as_text=True)
    assert "4 usuarios · 3 activos · 1 desactivados" in html and '<span class="tag">Sistemas</span>' in html
    assert "Administradores" in html                                  # root, por rol

    def names(query):
        page = visible(client.get(f"/admin/users?{query}").get_data(as_text=True))
        return {n for n in ("ana", "eva@x.com", "baja", "root") if f'aria-label="Seleccionar {n}"' in page}
    assert names("source=entra") == {"eva@x.com"}
    assert names("role=admin") == {"root"}
    assert names(f"group={gid}") == {"ana"}
    assert names("status=disabled") == {"baja"}


def test_list_pagination(app, admin):
    client, _ = admin
    for i in range(30):
        add_user(app, f"u{i:02d}")
    html = client.get("/admin/users").get_data(as_text=True)
    assert "1–25 de 31" in html and "page=2" in html
    html = client.get("/admin/users?page=2").get_data(as_text=True)
    assert "26–31 de 31" in html and ">u29<" in html


def test_bulk_actions(app, admin):
    client, token = admin
    gid = _group(app, "it", "Sistemas")
    a, b = add_user(app, "ana"), add_user(app, "beto")
    me = _user(app, "root")["id"]

    client.post("/admin/users/bulk", data={"_csrf": token, "action": "disable", "ids": [a, b, me]})
    assert not _user(app, "ana")["enabled"] and not _user(app, "beto")["enabled"]
    assert _user(app, "root")["enabled"]                              # no se desactiva a sí mismo
    html = client.get("/admin/users").get_data(as_text=True)
    assert "No puedes deshabilitar tu propia cuenta" in html

    client.post("/admin/users/bulk", data={"_csrf": token, "action": "enable", "ids": [a, b]})
    client.post("/admin/users/bulk", data={"_csrf": token, "action": "role_admin", "ids": [a]})
    assert _user(app, "ana")["role"] == "admin"
    client.post("/admin/users/bulk", data={"_csrf": token, "action": "add_group", "group_id": gid, "ids": [a, b]})
    assert "it" in _user(app, "beto")["groups"]
    resp = client.post("/admin/users/bulk", data={"_csrf": token, "action": "add_group", "ids": [a],
                                                  "next": "/admin/users?status=active"})
    assert resp.location == "/admin/users?status=active"
    with app.app_context():
        actions = [r["action"] for r in audit.recent(get_db(), 20)]
    assert {"user_disabled", "user_enabled", "user_updated", "group_member_added"} <= set(actions)


# --------------------------------------------------------------------------- A: ficha

def test_record_shows_effective_access_and_activity(app, admin):
    client, token = admin
    _group(app, "it", "Sistemas")
    ana = add_user(app, "ana")
    login(app.test_client(), "ana")
    _join(app, ana, "it")
    html = client.get(f"/admin/users/{ana}").get_data(as_text=True)
    assert "Acceso efectivo" in html and "grupo Sistemas" in html and "abierta a todos los usuarios" in html
    assert "Actividad reciente" in html and "<code>login</code>" in html        # la fixture logged inició sesión
    client.post(f"/admin/users/{ana}/status", data={"_csrf": token, "enabled": "0"})
    html = client.get(f"/admin/users/{ana}").get_data(as_text=True)
    assert "no ve ninguna carpeta" in html


# --------------------------------------------------------------------------- B: paneles

def test_panel_tabs_and_edit_returns_to_panel(app, admin):
    client, token = admin
    ana = add_user(app, "ana", display_name="Ana López")
    html = client.get(f"/admin/users/panel?u={ana}").get_data(as_text=True)
    assert '<h2 class="md-title">Ana López</h2>' in html and 'name="display_name"' in html
    for tab, text in (("groups", "Añadir a un grupo"), ("access", "Mi carpeta"), ("activity", "auditoría")):
        assert text in client.get(f"/admin/users/panel?u={ana}&tab={tab}").get_data(as_text=True)
    resp = client.post(f"/admin/users/{ana}", data={
        "_csrf": token, "display_name": "Ana L.", "email": "", "role": "user", "home_path": "", "enabled": "on",
        "next": f"/admin/users/panel?u={ana}&tab=profile"})
    assert resp.location.endswith(f"/admin/users/panel?u={ana}&tab=profile")
    assert _user(app, "ana")["display_name"] == "Ana L."


def test_cards_view_removed(admin):
    client, _ = admin
    assert client.get("/admin/users/cards").status_code == 404


def test_rail_link_goes_to_last_view(app, admin):
    client, _ = admin
    html = client.get("/admin/users").get_data(as_text=True)
    assert 'href="/admin/users/"' in html

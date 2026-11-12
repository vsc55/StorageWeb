"""Permisos por rol y alta/rol de usuarios de Entra ID."""
import io

import pytest

from storageweb.db.repositories import users

from tests.helpers import add_user, get_csrf, login, visible
from tests.sso_helpers import TENANT, entra_cfg, finish_login, start_login
from storageweb.web.context import get_db


# --------------------------------------------------------------------------- permisos por defecto

@pytest.fixture
def default_perms_app(make_app):
    return make_app({"permissions": {"user": {"upload": True, "download": True, "mkdir": True,
                                              "rename": False, "delete": False}}})


def test_user_default_permissions(default_perms_app, home):
    app = default_perms_app
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    resp = client.post("/upload/home/", data={"files": [(io.BytesIO(b"x"), "a.txt")]},
                       headers={"X-CSRF-Token": token, "Accept": "application/json"},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert client.get("/download/home/a.txt").data == b"x"
    html = visible(client.get("/f/home/").get_data(as_text=True))
    assert "Renombrar" not in html and "Eliminar" not in html
    assert client.post("/delete/home/a.txt", data={"_csrf": token}).status_code == 403
    assert client.post("/rename/home/a.txt", data={"_csrf": token, "name": "b"}).status_code == 403
    assert (home / "a.txt").exists()


def test_admin_has_all_permissions(default_perms_app, tmp_path):
    app = default_perms_app
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    token = get_csrf(client, "/f/home/")
    home = tmp_path / "data" / "homes" / "root"
    (home / "a.txt").write_text("x")
    assert client.post("/delete/home/a.txt", data={"_csrf": token}).status_code == 302
    assert not (home / "a.txt").exists()


def test_download_permission(make_app, home):
    app = make_app({"permissions": {"user": {"download": False}}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    client.get("/f/home/")  # crea la carpeta personal
    (home / "a.txt").write_text("x")
    assert client.get("/download/home/a.txt").status_code == 403
    assert "Descargar" not in visible(client.get("/f/home/").get_data(as_text=True))


# --------------------------------------------------------------------------- Entra: alta y rol

@pytest.fixture
def entra(make_app):
    def _make(**entra_overrides):
        return make_app({"auth": {"entra": entra_cfg(**entra_overrides)}})
    return _make


def _user(app, username):
    with app.app_context():
        return users.get_by_username(get_db(), username)


def test_auto_provision_default_role(entra, token_endpoint):
    app = entra(default_role="user")
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    assert finish_login(client, q["state"]).location == "/"
    assert _user(app, "juan@contoso.com")["role"] == "user"
    assert client.get("/admin/users").status_code == 403


def test_auto_provision_role_mapping_admin(entra, token_endpoint):
    app = entra(role_mappings={"StorageWeb.Admin": "admin"})
    client = app.test_client()
    token_endpoint.claims_extra = {"roles": ["StorageWeb.Admin"]}
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert _user(app, "juan@contoso.com")["role"] == "admin"
    assert client.get("/admin/users").status_code == 200


def test_role_sync_on_login(entra, token_endpoint):
    app = entra(role_mappings={"grp-admins": "admin"}, sync_role_on_login=True)
    client = app.test_client()
    token_endpoint.claims_extra = {"groups": ["GRP-ADMINS"]}
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert _user(app, "juan@contoso.com")["role"] == "admin"

    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    token_endpoint.claims_extra = {"groups": []}
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert _user(app, "juan@contoso.com")["role"] == "user"


def test_role_not_synced_keeps_manual_role(entra, token_endpoint):
    app = entra(role_mappings={"grp-admins": "admin"}, sync_role_on_login=False)
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    with app.app_context():
        users.update(get_db(), _user(app, "juan@contoso.com")["id"], role="admin")  # el admin lo promociona
    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert _user(app, "juan@contoso.com")["role"] == "admin"


def test_no_auto_provision_rejects_unknown(entra, token_endpoint):
    app = entra(auto_provision=False)
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    resp = finish_login(client, q["state"])
    assert "/login" in resp.location
    assert "no está dada de alta" in client.get("/login").get_data(as_text=True)
    assert _user(app, "juan@contoso.com") is None


def test_no_auto_provision_links_precreated_user(entra, token_endpoint):
    app = entra(auto_provision=False)
    add_user(app, "juan@contoso.com", password=None, source="entra", role="admin")
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    assert finish_login(client, q["state"]).location == "/"
    u = _user(app, "juan@contoso.com")
    assert u["external_id"] == "oid-juan" and u["role"] == "admin"
    # Un segundo usuario de Entra con otro oid no puede reclamar esa cuenta ya vinculada
    other = app.test_client()
    token_endpoint.claims_extra = {"oid": "oid-impostor"}
    _, q = start_login(other, token_endpoint)
    assert "/login" in finish_login(other, q["state"]).location


def test_provisioning_is_audited(entra, token_endpoint):
    from storageweb.db.repositories import audit

    app = entra()
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    with app.app_context():
        actions = [r["action"] for r in audit.recent(get_db(), 10)]
    assert "user_provisioned" in actions and "login" in actions


def test_provisioning_settings_from_web(make_app, token_endpoint):
    """El admin cambia el alta automática y el rol por defecto desde la web."""
    from tests.helpers import settings_form

    app = make_app({"auth": {"entra": entra_cfg()}})
    add_user(app, "root", role="admin")
    admin_client = app.test_client()
    login(admin_client, "root")
    data = settings_form(admin_client)
    data["entra_default_role"] = ["admin"]
    data["entra_client_secret"] = [""]
    assert admin_client.post("/admin/settings", data=data).status_code == 302

    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert _user(app, "juan@contoso.com")["role"] == "admin"

    data = settings_form(admin_client)
    data.pop("entra_auto_provision", None)
    assert admin_client.post("/admin/settings", data=data).status_code == 302
    token_endpoint.claims_extra = {"oid": "oid-otro", "preferred_username": "otro@contoso.com"}
    other = app.test_client()
    _, q = start_login(other, token_endpoint)
    assert "/login" in finish_login(other, q["state"]).location
    assert _user(app, "otro@contoso.com") is None

"""Ajustes de Entra ID: asistente de configuración y prueba de conexión."""
import pytest

from storageweb.providers.entra import check as entra_check
from tests.helpers import add_user, get_csrf, login


@pytest.fixture
def admin_client(app):
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return client, get_csrf(client, "/admin/settings/auth")


@pytest.fixture
def check_ok(monkeypatch):
    calls = []

    def fake(ecfg, redirect_uri):
        calls.append((ecfg["tenant_id"], redirect_uri))
        return [{"key": "metadata", "ok": True, "message": "El tenant existe."},
                {"key": "redirect", "ok": False, "message": "La Redirect URI no está registrada."}]
    monkeypatch.setattr(entra_check, "check", fake)
    return calls


def test_wizard_end_to_end(app, admin_client, check_ok):
    from storageweb.web.context import settings

    client, token = admin_client
    html = client.get("/admin/settings/entra/setup").get_data(as_text=True)
    assert "http://localhost/auth/entra/callback" in html                     # paso 1: URI calculada

    resp = client.post("/admin/settings/entra/setup", data={
        "_csrf": token, "step": "2", "entra_tenant_id": "t1", "entra_client_id": "c1",
        "entra_client_secret": "secreto", "entra_redirect_uri": "https://files.example.com/auth/entra/callback"})
    assert resp.location.endswith("/admin/settings/entra/setup?step=3")
    resp = client.post("/admin/settings/entra/setup", data={
        "_csrf": token, "step": "3", "provisioning": "manual", "default_role": "user",
        "allowed_groups": "", "admin_group": "StorageWeb.Admin"})
    assert resp.location.endswith("step=4")

    html = client.get("/admin/settings/entra/setup?step=4").get_data(as_text=True)
    assert check_ok == [("t1", "https://files.example.com/auth/entra/callback")]
    assert "La Redirect URI no está registrada." in html and "¿Activar Entra ID de todos modos?" in html

    resp = client.post("/admin/settings/entra/setup", data={"_csrf": token, "step": "4"})
    assert resp.location.endswith("/admin/settings/auth")
    with app.test_request_context():
        en = settings()["auth"]["entra"]
    assert en["enabled"] and not en["auto_provision"] and en["client_secret"] == "secreto"
    assert en["role_mappings"] == {"storageweb.admin": "admin"}
    assert "Iniciar sesión con Microsoft" in app.test_client().get("/login").get_data(as_text=True)


def test_wizard_validation_error(app, admin_client):
    client, token = admin_client
    resp = client.post("/admin/settings/entra/setup", data={
        "_csrf": token, "step": "2", "entra_tenant_id": "t1", "entra_client_id": "c1"})
    assert resp.status_code == 302                                           # sin activar, falta el secreto pero vale
    resp = client.post("/admin/settings/entra/setup", data={"_csrf": token, "step": "4"})
    assert resp.status_code == 400 and "client_secret" in resp.get_data(as_text=True)


def test_test_connection_button(app, admin_client, check_ok):
    client, token = admin_client
    html = client.get("/admin/settings/auth").get_data(as_text=True)
    assert "Sin comprobar todavía" in html
    client.post("/admin/settings/entra/setup", data={
        "_csrf": token, "step": "2", "entra_tenant_id": "t1", "entra_client_id": "c1", "entra_client_secret": "x"})
    resp = client.post("/admin/settings/entra/test", data={"_csrf": token, "next": "/admin/settings/auth"})
    assert resp.location.endswith("/admin/settings/auth")
    html = client.get("/admin/settings/auth").get_data(as_text=True)
    assert "Problemas en la última comprobación" in html and "La Redirect URI no está registrada." in html


def test_settings_require_admin(logged):
    client, token = logged
    for url in ("/admin/settings/general", "/admin/settings/entra/setup"):
        assert client.get(url).status_code == 403
    assert client.post("/admin/settings/entra/test", data={"_csrf": token}).status_code == 403

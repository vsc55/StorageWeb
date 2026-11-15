"""Botón «Registrar en Entra ID»: código de dispositivo, sondeo y guardado de los ajustes."""
import pytest

from storageweb.providers.entra import register as er
from tests.helpers import add_user, get_csrf, login

JSON = {"Accept": "application/json"}


@pytest.fixture
def admin_client(make_app):
    app = make_app({"network": {"public_url": "files.example.com"}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return app, client, get_csrf(client, "/admin/settings/auth")


@pytest.fixture
def microsoft(monkeypatch):
    """Simula Microsoft: el primer sondeo está pendiente, el segundo devuelve el token."""
    state = {"polls": 0, "registered": None}

    def device_start():
        return {"device_code": "dc", "user_code": "WXYZ-9876", "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900, "interval": 5}

    def device_poll(code):
        state["polls"] += 1
        return {"error": "authorization_pending"} if state["polls"] == 1 else {"access_token": "tok"}

    def register_app(token, **options):
        state["registered"] = options
        return {"tenant_id": "tenant-1", "client_id": "client-1", "client_secret": "s3cr3t",
                "secret_expires": "2028-11-13T00:00:00Z", "object_id": "o", "app_roles": options["app_roles"],
                "warnings": ["Aviso de prueba"], "portal_url": "https://entra.microsoft.com/x"}

    monkeypatch.setattr(er, "device_start", device_start)
    monkeypatch.setattr(er, "device_poll", device_poll)
    monkeypatch.setattr(er, "register_app", register_app)
    return state


def test_register_flow_end_to_end(admin_client, microsoft):
    from storageweb.web.context import settings

    app, client, token = admin_client
    html = client.get("/admin/settings/entra/register").get_data(as_text=True)
    assert "https://files.example.com/auth/entra/callback" in html and "Iniciar sesión con Microsoft y registrar" in html

    client.post("/admin/settings/entra/register", data={"_csrf": token, "app_name": "Archivos", "app_roles": "on",
                                                        "group_claims": "on"})
    html = client.get("/admin/settings/entra/register").get_data(as_text=True)
    assert 'value="WXYZ-9876"' in html and "microsoft.com/devicelogin" in html

    resp = client.post("/admin/settings/entra/register/poll", headers={**JSON, "X-CSRF-Token": token})
    assert resp.get_json()["status"] == "pending"
    resp = client.post("/admin/settings/entra/register/poll", headers={**JSON, "X-CSRF-Token": token})
    data = resp.get_json()
    assert data["status"] == "complete" and data["redirect"].endswith("/admin/settings/entra/setup?step=4")
    assert microsoft["registered"]["redirect_uri"] == "https://files.example.com/auth/entra/callback"
    assert microsoft["registered"]["name"] == "Archivos" and microsoft["registered"]["group_claims"]

    with app.test_request_context():
        en = settings()["auth"]["entra"]
    assert (en["tenant_id"], en["client_id"], en["client_secret"]) == ("tenant-1", "client-1", "s3cr3t")
    assert en["role_mappings"] == {"storageweb.admin": "admin"} and not en["enabled"]
    assert "redirect_uri" not in en            # no se guarda: se calcula de la dirección pública
    assert "entra_app_registered" in client.get("/admin/audit").get_data(as_text=True)

    # el paso 4 del asistente muestra lo creado y sus avisos (y luego ya no)
    from storageweb.providers.entra import check as entra_check
    entra_check_check = entra_check.check
    entra_check.check = lambda ecfg, uri, secret_is_new=False, **_kw: [{"key": "metadata", "ok": True, "message": "ok"}]
    try:
        html = client.get(data["redirect"]).get_data(as_text=True)
        assert "client-1" in html and "Aviso de prueba" in html
        assert "Aviso de prueba" not in client.get(data["redirect"]).get_data(as_text=True)
    finally:
        entra_check.check = entra_check_check
    # el código ya se canjeó
    assert client.post("/admin/settings/entra/register/poll", headers={**JSON, "X-CSRF-Token": token}).get_json()["status"] == "expired"


def test_poll_without_javascript_redirects(admin_client, microsoft):
    _app, client, token = admin_client
    client.post("/admin/settings/entra/register", data={"_csrf": token, "app_name": "X"})
    resp = client.post("/admin/settings/entra/register/poll", data={"_csrf": token}, follow_redirects=True)
    assert "todavía no ha confirmado" in resp.get_data(as_text=True)
    resp = client.post("/admin/settings/entra/register/poll", data={"_csrf": token})
    assert resp.location.endswith("/admin/settings/entra/setup?step=4")


def test_declined_and_cancel(admin_client, monkeypatch, microsoft):
    _app, client, token = admin_client
    monkeypatch.setattr(er, "device_poll", lambda code: {"error": "authorization_declined",
                                                         "error_description": "AADSTS70000: declined"})
    client.post("/admin/settings/entra/register", data={"_csrf": token, "app_name": "X"})
    data = client.post("/admin/settings/entra/register/poll", headers={**JSON, "X-CSRF-Token": token}).get_json()
    assert data["status"] == "error" and "declined" in data["message"]
    client.post("/admin/settings/entra/register", data={"_csrf": token, "app_name": "X"})
    client.post("/admin/settings/entra/register/cancel", data={"_csrf": token})
    assert 'value="WXYZ-9876"' not in client.get("/admin/settings/entra/register").get_data(as_text=True)


def test_http_public_name_is_refused(make_app, microsoft):
    app = make_app({"network": {"public_url": "http://files.example.com"}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    token = get_csrf(client, "/admin/settings/entra/register")
    html = client.get("/admin/settings/entra/register").get_data(as_text=True)
    assert "solo acepta direcciones de vuelta HTTPS" in html
    client.post("/admin/settings/entra/register", data={"_csrf": token, "app_name": "X"})
    assert 'value="WXYZ-9876"' not in client.get("/admin/settings/entra/register").get_data(as_text=True)


def test_register_requires_admin(logged):
    client, token = logged
    assert client.get("/admin/settings/entra/register").status_code == 403
    assert client.post("/admin/settings/entra/register/poll", data={"_csrf": token}).status_code == 403

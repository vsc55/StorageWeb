"""Bloqueo de IPs, mantenimiento (copias, compactación, CSV), marca y extras de Entra ID desde la web."""
import io
import subprocess  # noqa: F401  (los comandos de la CLI se prueban en proceso)

import pytest

from storageweb.core import ipban
from storageweb.db.repositories import ip_rules
from storageweb.providers.entra import check as entra_check, directory as entra_directory, register as entra_register
from storageweb.web.context import get_db
from tests.helpers import PASSWORD, add_user, get_csrf, login

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
OTHER_IP = {"REMOTE_ADDR": "203.0.113.50"}


@pytest.fixture(autouse=True)
def fresh_rules():
    ipban.invalidate()
    yield
    ipban.invalidate()


# --------------------------------------------------------------------------- IPs

def test_blocked_ip_gets_403(app, admin):
    client, token = admin
    resp = client.post("/admin/settings/security/ip", data={"_csrf": token, "kind": "ban", "network": "203.0.113.0/24",
                                                            "minutes": "0", "reason": "pruebas"})
    assert resp.status_code == 302
    blocked = app.test_client()
    resp = blocked.get("/login", environ_base=OTHER_IP)
    assert resp.status_code == 403 and "bloqueada" in resp.get_data(as_text=True)
    html = client.get("/admin/settings/ips").get_data(as_text=True)
    assert "203.0.113.0/24" in html and "pruebas" in html
    with app.app_context():
        rule = ip_rules.list_rules(get_db(), "ban")[0]
    client.post(f"/admin/settings/security/ip/{rule['id']}/delete", data={"_csrf": token})
    assert blocked.get("/login", environ_base=OTHER_IP).status_code == 200


def test_cannot_block_own_address(app, admin):
    client, token = admin
    html = client.post("/admin/settings/security/ip", data={"_csrf": token, "kind": "ban", "network": "127.0.0.1"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes bloquear la dirección que estás usando" in html


def test_automatic_ban_from_failed_logins(make_app):
    app = make_app({"security": {"ipban_threshold": 3, "max_login_failures": 50}})
    add_user(app, "ana")
    client = app.test_client()
    for _ in range(3):
        token = get_csrf(client, "/login") if False else None
        page = client.get("/login", environ_base=OTHER_IP).get_data(as_text=True)
        import re
        csrf = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
        client.post("/login", data={"_csrf": csrf, "username": "ana", "password": "mala"}, environ_base=OTHER_IP)
    assert client.get("/login", environ_base=OTHER_IP).status_code == 403
    assert app.test_client().get("/login").status_code == 200          # 127.0.0.1 nunca se bloquea
    assert token is None


def test_cli_ip_unban(app, make_app):
    from storageweb import cli

    with app.app_context():
        ipban.ban(get_db(), "198.51.100.7", by="root")
    cfg_path = app.config["SW"]["_config_path"]
    assert cli.main(["--config", cfg_path, "ip-unban", "--all"]) == 0
    with app.app_context():
        assert ip_rules.list_rules(get_db(), "ban") == []
    assert cli.main(["--config", cfg_path, "ip-allow", "10.0.0.0/8"]) == 0
    assert cli.main(["--config", cfg_path, "ip-list"]) == 0


# --------------------------------------------------------------------------- mantenimiento

def test_backups_from_the_web(app, admin):
    client, token = admin
    resp = client.post("/admin/settings/maintenance/backups", data={"_csrf": token})
    assert resp.status_code == 302
    html = client.get("/admin/settings/backups").get_data(as_text=True)
    import re
    name = re.search(r"<code>(storageweb-backup-[^<]+)</code>", html).group(1)
    resp = client.get(f"/admin/settings/maintenance/backups/{name}")
    assert resp.status_code == 200 and resp.data[:2] == b"\x1f\x8b" and "attachment" in resp.headers["Content-Disposition"]
    resp.close()  # en Windows el fichero no se puede borrar mientras la respuesta lo tenga abierto
    assert client.get("/admin/settings/maintenance/backups/..%2Fconfig.json").status_code == 404
    client.post(f"/admin/settings/maintenance/backups/{name}/delete", data={"_csrf": token})
    assert f"<code>{name}</code>" not in client.get("/admin/settings/backups").get_data(as_text=True)


def test_vacuum_purge_and_csv(app, admin):
    client, token = admin
    assert client.post("/admin/settings/maintenance/vacuum", data={"_csrf": token}).status_code == 302
    html = client.post("/admin/settings/maintenance/purge", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "Define antes la retención" in html
    resp = client.get("/admin/audit/export.csv?action=login")
    text = resp.data.decode("utf-8-sig")
    assert resp.mimetype == "text/csv" and text.splitlines()[0] == "ts,username,action,target,ip,detail"
    assert ",root,login," in text and "db_vacuum" not in text


# --------------------------------------------------------------------------- marca

def test_logo_and_color(app, admin):
    client, token = admin
    resp = client.post("/admin/settings/branding/logo", data={"_csrf": token, "logo": (io.BytesIO(PNG), "mi-logo.png")},
                       content_type="multipart/form-data")
    assert resp.status_code == 302
    html = client.get("/f/home/").get_data(as_text=True)
    assert "/brand/logo?v=" in html
    assert app.test_client().get("/brand/logo").data == PNG                  # también sin iniciar sesión
    data = {"_csrf": token, "app_name": "Archivos", "default_locale": "es", "custom_color": "on", "primary_color": "#AA3300"}
    assert client.post("/admin/settings/general", data=data).status_code == 302
    html = app.test_client().get("/login").get_data(as_text=True)
    assert "/brand.css?v=" in html
    assert "--primary: #aa3300" in client.get("/brand.css").get_data(as_text=True)
    client.post("/admin/settings/branding/logo/delete", data={"_csrf": token})
    assert app.test_client().get("/brand/logo").status_code == 404


def test_svg_logo_is_sandboxed_and_bad_files_refused(app, admin):
    client, token = admin
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    client.post("/admin/settings/branding/logo", data={"_csrf": token, "logo": (io.BytesIO(svg), "l.svg")},
                content_type="multipart/form-data")
    resp = app.test_client().get("/brand/logo")
    assert resp.mimetype == "image/svg+xml" and "sandbox" in resp.headers["Content-Security-Policy"]
    html = client.post("/admin/settings/branding/logo", data={"_csrf": token, "logo": (io.BytesIO(b"GIF89a"), "l.gif")},
                       content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)
    assert "PNG, JPEG, WebP o SVG" in html


# --------------------------------------------------------------------------- Entra ID

@pytest.fixture
def entra_admin(make_app, monkeypatch):
    app = make_app({"auth": {"entra": {"tenant_id": "t1", "client_id": "c1", "client_secret": "s",
                                       "secret_expires": "2000-01-01"}}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    monkeypatch.setattr(entra_register, "device_start", lambda: {
        "device_code": "dc", "user_code": "CODE-1", "verification_uri": "https://microsoft.com/devicelogin"})
    monkeypatch.setattr(entra_register, "device_poll", lambda code: {"access_token": "tok"})
    return app, client, get_csrf(client, "/admin/settings/auth")


def test_secret_expiry_banner_and_rotation(entra_admin, monkeypatch):
    from storageweb.web.context import settings

    app, client, token = entra_admin
    html = client.get("/f/home/").get_data(as_text=True)
    assert "El secreto de Entra ID ha caducado" in html and "Renovar el secreto" in html
    monkeypatch.setattr(entra_register, "rotate_secret", lambda tok, cid: {
        "client_secret": "nuevo", "secret_expires": "2099-01-01T00:00:00+00:00"})
    client.post("/admin/settings/entra/rotate", data={"_csrf": token})
    assert 'value="CODE-1"' in client.get("/admin/settings/entra/register").get_data(as_text=True)
    resp = client.post("/admin/settings/entra/register/poll", data={"_csrf": token})
    assert resp.location.endswith("/admin/settings/auth")
    with app.test_request_context():
        en = settings()["auth"]["entra"]
    assert en["client_secret"] == "nuevo" and en["secret_expires"].startswith("2099")
    assert "Renovar el secreto" not in client.get("/f/home/").get_data(as_text=True)
    assert "entra_secret_rotated" in client.get("/admin/audit").get_data(as_text=True)


def test_grant_groups_and_group_names(entra_admin, monkeypatch):
    app, client, token = entra_admin
    granted = []
    monkeypatch.setattr(entra_register, "grant_group_read", lambda tok, cid: granted.append(cid))
    client.post("/admin/settings/entra/grant-groups", data={"_csrf": token})
    client.post("/admin/settings/entra/register/poll", data={"_csrf": token})
    assert granted == ["c1"]

    gid = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(entra_directory, "names_for", lambda ecfg, ids: {gid: "Sistemas"} if gid in ids else {})
    monkeypatch.setattr(entra_directory, "search_groups", lambda ecfg, q: [{"id": gid, "name": "Sistemas"}])
    uid = add_user(app, "eva@x.com", password=None, source="entra", external_id="o-eva")
    from storageweb.core import groups as gc
    with app.app_context():
        gc.sync_external(get_db(), uid, "entra", [gid])
    html = client.get("/admin/groups/list").get_data(as_text=True)
    assert "<strong>Sistemas</strong>" in html and "label=Sistemas" in html
    assert client.get("/admin/groups/directory/entra/search?q=Sis").get_json()["groups"][0]["name"] == "Sistemas"
    html = client.get(f"/admin/users/{uid}").get_data(as_text=True)
    assert "<strong>Sistemas</strong>" in html


def test_check_shows_grant_button_when_groups_missing(entra_admin, monkeypatch):
    _app, client, token = entra_admin
    monkeypatch.setattr(entra_check, "check", lambda ecfg, uri: [
        {"key": "secret", "ok": True, "message": "ok"}, {"key": "groups", "ok": False, "message": "sin permiso"}])
    client.post("/admin/settings/entra/test", data={"_csrf": token})
    html = client.get("/admin/settings/auth").get_data(as_text=True)
    assert "Conceder lectura de grupos" in html
    assert PASSWORD

import re

import pytest

from src.db import users

from .conftest import PASSWORD, add_user, get_csrf, login


def _user(app, username):
    with app.app_context():
        return users.get_by_username(username)


# --------------------------------------------------------------------------- acceso

@pytest.mark.parametrize("url", ["/admin/", "/admin/users", "/admin/users/new", "/admin/settings", "/admin/audit"])
def test_admin_requires_login(client, url):
    resp = client.get(url)
    assert resp.status_code == 302 and "/login" in resp.location


@pytest.mark.parametrize("url", ["/admin/users", "/admin/users/new", "/admin/settings", "/admin/audit"])
def test_user_role_forbidden(logged, url):
    client, _ = logged
    assert client.get(url).status_code == 403


def test_user_role_cannot_post_admin(logged):
    client, token = logged
    resp = client.post("/admin/users/new", data={"_csrf": token, "username": "x", "source": "local",
                                                 "password": PASSWORD, "role": "admin"})
    assert resp.status_code == 403


def test_admin_link_only_for_admin(app, client, logged):
    c, _ = logged
    assert "Administración" not in c.get("/f/home/").get_data(as_text=True)


def test_admin_sees_admin_link(admin):
    client, _ = admin
    assert "Administración" in client.get("/f/home/").get_data(as_text=True)
    assert client.get("/admin/").location.endswith("/admin/users")


# --------------------------------------------------------------------------- usuarios

def test_list_and_search(app, admin):
    client, _ = admin
    add_user(app, "ana", display_name="Ana López")
    add_user(app, "beto")
    html = client.get("/admin/users").get_data(as_text=True)
    assert "ana" in html and "beto" in html and "root" in html
    html = client.get("/admin/users?q=López").get_data(as_text=True)
    assert "ana" in html and "beto" not in html


def test_create_local_user(app, admin):
    client, token = admin
    resp = client.post("/admin/users/new", data={
        "_csrf": token, "username": "nuevo", "source": "local", "password": PASSWORD,
        "display_name": "Nuevo", "role": "user", "groups": "rrhh, IT", "enabled": "on"})
    assert resp.status_code == 302
    u = _user(app, "nuevo")
    assert u["source"] == "local" and u["role"] == "user" and u["groups"] == "it,rrhh"
    other = app.test_client()
    assert login(other, "nuevo").status_code == 302


def test_create_user_validation(app, admin):
    client, token = admin
    base = {"_csrf": token, "source": "local", "role": "user", "enabled": "on"}
    html = client.post("/admin/users/new", data={**base, "username": "x", "password": "corta"}).get_data(as_text=True)
    assert "al menos" in html and _user(app, "x") is None
    html = client.post("/admin/users/new", data={**base, "username": "../mal", "password": PASSWORD}).get_data(as_text=True)
    assert "no válido" in html
    html = client.post("/admin/users/new", data={**base, "username": "root", "password": PASSWORD}).get_data(as_text=True)
    assert "Ya existe" in html
    html = client.post("/admin/users/new", data={**base, "username": "y", "password": PASSWORD,
                                                 "role": "dios"}).get_data(as_text=True)
    assert "Rol no válido" in html


def test_precreate_entra_user(app, admin):
    client, token = admin
    client.post("/admin/users/new", data={"_csrf": token, "username": "Juan@Contoso.com",
                                          "source": "entra", "role": "admin", "enabled": "on"})
    u = _user(app, "juan@contoso.com")
    assert u["source"] == "entra" and u["password_hash"] is None and u["external_id"] is None
    assert u["role"] == "admin"


def test_edit_user(app, admin, tmp_path):
    client, token = admin
    uid = add_user(app, "ana")
    resp = client.post(f"/admin/users/{uid}", data={
        "_csrf": token, "display_name": "Ana L.", "email": "ana@x.com", "role": "admin",
        "groups": "finanzas", "home_path": str(tmp_path / "h"), "enabled": "on"})
    assert resp.status_code == 302
    u = _user(app, "ana")
    assert u["role"] == "admin" and u["display_name"] == "Ana L." and u["groups"] == "finanzas"
    assert u["home_path"] == str(tmp_path / "h")


def test_reset_password(app, admin):
    client, token = admin
    uid = add_user(app, "ana")
    client.post(f"/admin/users/{uid}", data={"_csrf": token, "role": "user", "enabled": "on",
                                             "password": "nueva-contraseña-1"})
    other = app.test_client()
    assert login(other, "ana", "nueva-contraseña-1").status_code == 302


def test_disable_user(app, admin):
    client, token = admin
    uid = add_user(app, "ana")
    client.post(f"/admin/users/{uid}", data={"_csrf": token, "role": "user"})  # sin 'enabled'
    assert not _user(app, "ana")["enabled"]
    assert "incorrectos" in login(app.test_client(), "ana").get_data(as_text=True)


def test_cannot_demote_or_disable_self(app, admin):
    client, token = admin
    me = _user(app, "root")
    html = client.post(f"/admin/users/{me['id']}", data={"_csrf": token, "role": "user", "enabled": "on"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes quitarte" in html
    html = client.post(f"/admin/users/{me['id']}", data={"_csrf": token, "role": "admin"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes deshabilitar" in html
    assert _user(app, "root")["role"] == "admin" and _user(app, "root")["enabled"]


def test_last_admin_guard(app, admin):
    client, token = admin
    # Hay otro admin deshabilitado: no cuenta. Al intentar borrar a root (uno mismo) falla.
    me = _user(app, "root")
    html = client.post(f"/admin/users/{me['id']}/delete", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes eliminar tu propia cuenta" in html
    # Con un segundo admin, se puede degradar al primero desde el segundo
    uid2 = add_user(app, "admin2", role="admin")
    other = app.test_client()
    login(other, "admin2")
    tok2 = get_csrf(other, "/admin/users")
    assert other.post(f"/admin/users/{me['id']}", data={"_csrf": tok2, "role": "user", "enabled": "on"}
                      ).status_code == 302
    # ...pero ahora admin2 es el último y no puede ser degradado por nadie más
    with app.app_context():
        assert users.count_admins() == 1
    assert _user(app, "admin2")["id"] == uid2


def test_delete_user(app, admin, tmp_path):
    client, token = admin
    uid = add_user(app, "ana")
    home = tmp_path / "data" / "homes" / "ana"
    home.mkdir(parents=True)
    (home / "dato.txt").write_text("x")
    resp = client.post(f"/admin/users/{uid}/delete", data={"_csrf": token})
    assert resp.status_code == 302
    assert _user(app, "ana") is None
    assert (home / "dato.txt").exists()  # los archivos se conservan


def test_edit_unknown_user(admin):
    client, token = admin
    assert client.get("/admin/users/9999").status_code == 404
    assert client.post("/admin/users/9999/delete", data={"_csrf": token}).status_code == 404


# --------------------------------------------------------------------------- ajustes

def _settings_form(client) -> dict:
    """Lee el formulario de ajustes tal como lo enviaría el navegador."""
    html = client.get("/admin/settings").get_data(as_text=True)
    form = re.search(r'<form method="post" class="settings">(.*?)</form>', html, re.S).group(1)
    data: dict = {}
    for m in re.finditer(r'<input([^>]*)>', form):
        attrs = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', m.group(1)))
        name, typ = attrs.get("name"), attrs.get("type", "text")
        if not name:
            continue
        if typ == "checkbox":
            if " checked" in m.group(1):
                data.setdefault(name, []).append("on")
        else:
            data.setdefault(name, []).append(attrs.get("value", ""))
    for m in re.finditer(r'<select name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
        sel = re.search(r'<option value="([^"]*)"[^>]*selected', m.group(2)) or \
            re.search(r'<option value="([^"]*)"', m.group(2))
        data.setdefault(m.group(1), []).append(sel.group(1))
    for m in re.finditer(r'<textarea name="([^"]+)"[^>]*>(.*?)</textarea>', form, re.S):
        data[m.group(1)] = [m.group(2)]
    return data


def test_settings_page_renders(admin):
    client, _ = admin
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Carpetas compartidas" in html and "Entra ID" in html and "Permisos" in html


def test_settings_roundtrip_unchanged(app, admin):
    client, token = admin
    data = _settings_form(client)
    resp = client.post("/admin/settings", data=data)
    assert resp.status_code == 302, resp.get_data(as_text=True)


def test_settings_change_applies_immediately(app, admin, tmp_path):
    client, _ = admin
    (tmp_path / "equipo").mkdir()
    data = _settings_form(client)
    data.update({"app_name": ["Mi Nube"], "share_name": ["equipo"], "share_label": ["Equipo"],
                 "share_path": [str(tmp_path / "equipo")], "share_read_only": ["1"],
                 "share_users": ["*"], "share_groups": [""]})
    assert client.post("/admin/settings", data=data).status_code == 302
    html = client.get("/f/home/").get_data(as_text=True)
    assert "Mi Nube" in html and "Equipo" in html
    assert client.get("/f/equipo/").status_code == 200


def test_settings_permissions_affect_users(app, admin):
    client, _ = admin
    data = _settings_form(client)
    data.pop("perm_upload", None)
    assert client.post("/admin/settings", data=data).status_code == 302
    add_user(app, "ana")
    user_client = app.test_client()
    login(user_client, "ana")
    assert "Subir archivos" not in user_client.get("/f/home/").get_data(as_text=True)
    tok = get_csrf(user_client, "/f/home/")
    assert user_client.post("/upload/home/", data={"_csrf": tok}).status_code == 403
    # el admin conserva todos los permisos
    assert "Subir archivos" in client.get("/f/home/").get_data(as_text=True)


def test_settings_invalid_not_saved(app, admin):
    client, _ = admin
    data = _settings_form(client)
    data["home_template"] = ["/srv/sin-placeholder"]
    resp = client.post("/admin/settings", data=data)
    assert resp.status_code == 400
    assert "{username}" in resp.get_data(as_text=True)
    data = _settings_form(client)
    assert data["home_template"][0] != "/srv/sin-placeholder"


def test_settings_cannot_disable_all_logins(app, admin):
    client, _ = admin
    data = _settings_form(client)
    data.pop("local_enabled", None)
    resp = client.post("/admin/settings", data=data)
    assert resp.status_code == 400 and "al menos un" in resp.get_data(as_text=True)


def test_settings_bad_role_mapping(app, admin):
    client, _ = admin
    data = _settings_form(client)
    data["entra_role_mappings"] = ["GrupoX = superadmin"]
    assert client.post("/admin/settings", data=data).status_code == 400
    data["entra_role_mappings"] = ["sin igual"]
    assert client.post("/admin/settings", data=data).status_code == 400


def test_secret_kept_when_blank_and_never_shown(app, admin):
    from src.config import settings

    client, _ = admin
    data = _settings_form(client)
    data.update({"entra_enabled": ["on"], "entra_tenant_id": ["t1"], "entra_client_id": ["c1"],
                 "entra_client_secret": ["muy-secreto"]})
    assert client.post("/admin/settings", data=data).status_code == 302
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "muy-secreto" not in html and "configurado" in html

    data = _settings_form(client)
    assert data["entra_client_secret"] == [""]
    data["entra_button_label"] = ["Entrar con Microsoft"]
    assert client.post("/admin/settings", data=data).status_code == 302
    with app.test_request_context():
        assert settings.current()["auth"]["entra"]["client_secret"] == "muy-secreto"
    assert "Entrar con Microsoft" in app.test_client().get("/login").get_data(as_text=True)


def test_settings_reset(app, admin):
    client, token = admin
    data = _settings_form(client)
    data["app_name"] = ["Temporal"]
    client.post("/admin/settings", data=data)
    assert "Temporal" in client.get("/f/home/").get_data(as_text=True)
    client.post("/admin/settings/reset", data={"_csrf": token})
    assert "Temporal" not in client.get("/f/home/").get_data(as_text=True)


def test_settings_audited(app, admin):
    client, _ = admin
    client.post("/admin/settings", data=_settings_form(client))
    html = client.get("/admin/audit?action=settings_updated").get_data(as_text=True)
    assert "settings_updated" in html and "root" in html


def test_audit_page_filters(app, admin):
    client, _ = admin
    login(app.test_client(), "nadie", "x")
    html = client.get("/admin/audit?action=login_failed").get_data(as_text=True)
    assert "nadie" in html
    html = client.get("/admin/audit?user=root").get_data(as_text=True)
    assert "nadie" not in html

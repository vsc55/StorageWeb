import pytest

from storageweb.db.repositories import users

from tests.helpers import PASSWORD, add_user, get_csrf, login, page_form, settings_form, visible, U
from storageweb.web.context import get_db


def _user(app, username):
    with app.app_context():
        return users.get_by_username(get_db(), username)


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
    assert "Administración" not in visible(c.get("/f/home/").get_data(as_text=True))


def test_admin_sees_admin_link(admin):
    client, _ = admin
    assert "Administración" in client.get("/f/home/").get_data(as_text=True)
    html = client.get("/admin/").get_data(as_text=True)  # el Resumen
    assert "Resumen" in html and "Personas" in html and "Acceso" in html


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
    resp = client.post(f"/admin/users/{U(uid)}", data={
        "_csrf": token, "display_name": "Ana L.", "email": "ana@x.com", "role": "admin",
        "home_path": str(tmp_path / "h"), "enabled": "on"})
    assert resp.status_code == 302
    u = _user(app, "ana")
    assert u["role"] == "admin" and u["display_name"] == "Ana L."
    assert u["home_path"] == str(tmp_path / "h")


def test_reset_password(app, admin):
    client, token = admin
    uid = add_user(app, "ana")
    ana_client = app.test_client()
    assert login(ana_client, "ana").status_code == 302
    # Editar ya no cambia la contraseña: tiene su propio botón, en la lista y en los paneles
    client.post(f"/admin/users/{U(uid)}", data={"_csrf": token, "role": "user", "enabled": "on",
                                             "password": "otra-contraseña-9"})
    assert login(app.test_client(), "ana", "otra-contraseña-9").status_code == 200
    url = f"/admin/users/{U(uid)}/password"
    assert url in client.get("/admin/users").get_data(as_text=True)
    record = client.get(f"/admin/users/{U(uid)}").get_data(as_text=True)
    assert url not in record and 'name="password"' not in record                # ni campo ni botón en la ficha
    for title in ("Perfil", "Acceso", "Carpeta personal", "Cuota (MB)", "Inicio de sesión y seguridad"):
        assert title in record
    page = client.get(url).get_data(as_text=True)
    assert 'name="repeat_password"' in page
    html = client.post(url, data={"_csrf": token, "password": "nueva-contraseña-1",
                                  "repeat_password": "otra"}).get_data(as_text=True)
    assert "no coinciden" in html
    assert "10" in client.post(url, data={"_csrf": token, "password": "corta", "repeat_password": "corta"}).get_data(
        as_text=True)
    resp = client.post(url, data={"_csrf": token, "password": "nueva-contraseña-1", "repeat_password": "nueva-contraseña-1",
                                  "next": "/admin/users"})
    assert resp.status_code == 302 and resp.location.endswith("/admin/users")
    assert login(app.test_client(), "ana", "nueva-contraseña-1").status_code == 302
    assert ana_client.get("/f/home/").status_code == 302                       # sus sesiones se cerraron
    with app.app_context():
        from storageweb.db.repositories import audit
        row = audit.recent(get_db(), 5, action="password_reset_by_admin")[0]
    assert row["target"] == "ana" and row["detail"] == "sessions_closed=1"


def test_reset_password_not_for_self_or_sso(app, admin):
    """El servidor no se fía de los botones desactivados: las peticiones hechas a mano también se rechazan."""
    client, token = admin
    me = _user(app, "root")
    new = {"_csrf": token, "password": "x" * 12, "repeat_password": "x" * 12}
    assert client.get(f"/admin/users/{U(me['id'])}/password").location.endswith("/profile/security#password")
    assert client.post(f"/admin/users/{U(me['id'])}/password", data=new).status_code == 403
    assert login(app.test_client(), "root").status_code == 302                  # la suya no cambió
    uid = add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-1")
    page = client.get("/admin/users").get_data(as_text=True)
    assert f"/admin/users/{U(uid)}/password" not in page and "disabled" in page   # el botón está, desactivado
    assert client.post(f"/admin/users/{U(uid)}/password", data=new).status_code == 403
    assert client.get(f"/admin/users/{U(uid)}/password").status_code == 403
    assert _user(app, "juan@contoso.com")["password_hash"] is None
    with app.app_context():
        from storageweb.db.repositories import audit
        assert audit.recent(get_db(), 1, action="access_denied")
    # Tampoco por el núcleo, venga de donde venga la llamada
    from storageweb.core import accounts
    with app.app_context():
        with pytest.raises(accounts.AccountError):
            accounts.set_password(get_db(), me, me, "y" * 12)
        with pytest.raises(accounts.AccountError):
            accounts.set_password(get_db(), _user(app, "juan@contoso.com"), me, "y" * 12)


def test_disable_is_checked_by_the_server(app, admin):
    """Desactivarse a uno mismo o al último administrador, a mano (fila, en bloque o editando), no cuela."""
    client, token = admin
    me = _user(app, "root")
    client.post(f"/admin/users/{U(me['id'])}/status", data={"_csrf": token, "enabled": "0"})
    client.post("/admin/users/bulk", data={"_csrf": token, "action": "disable", "ids": [U(me["id"])]})
    client.post(f"/admin/users/{U(me['id'])}", data={"_csrf": token, "role": "admin"})
    assert _user(app, "root")["enabled"]
    with app.app_context():
        from storageweb.core import accounts
        with pytest.raises(accounts.AccountError):
            accounts.set_enabled(get_db(), me, me, False)


def test_disable_user(app, admin):
    client, token = admin
    uid = add_user(app, "ana")
    # Editar no activa ni desactiva (una sola forma de hacerlo: su botón, con confirmación)
    client.post(f"/admin/users/{U(uid)}", data={"_csrf": token, "role": "user"})
    assert _user(app, "ana")["enabled"]
    assert 'name="enabled"' not in client.get(f"/admin/users/{U(uid)}").get_data(as_text=True).split("danger-zone")[0]
    client.post(f"/admin/users/{U(uid)}/status", data={"_csrf": token, "enabled": "0"})
    assert not _user(app, "ana")["enabled"]
    assert "incorrectos" in login(app.test_client(), "ana").get_data(as_text=True)
    client.post(f"/admin/users/{U(uid)}", data={"_csrf": token, "role": "user", "enabled": "on"})
    assert not _user(app, "ana")["enabled"]                                       # ni con la casilla a mano


def test_cannot_demote_or_disable_self(app, admin):
    client, token = admin
    me = _user(app, "root")
    html = client.post(f"/admin/users/{U(me['id'])}", data={"_csrf": token, "role": "user", "enabled": "on"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes quitarte" in html
    html = client.post(f"/admin/users/{U(me['id'])}/status", data={"_csrf": token, "enabled": "0"},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes deshabilitar" in html
    assert _user(app, "root")["role"] == "admin" and _user(app, "root")["enabled"]


def test_last_admin_guard(app, admin):
    client, token = admin
    # Hay otro admin deshabilitado: no cuenta. Al intentar borrar a root (uno mismo) falla.
    me = _user(app, "root")
    html = client.post(f"/admin/users/{U(me['id'])}/delete", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "No puedes eliminar tu propia cuenta" in html
    # Con un segundo admin, se puede degradar al primero desde el segundo
    uid2 = add_user(app, "admin2", role="admin")
    other = app.test_client()
    login(other, "admin2")
    tok2 = get_csrf(other, "/admin/users")
    assert other.post(f"/admin/users/{U(me['id'])}", data={"_csrf": tok2, "role": "user", "enabled": "on"}
                      ).status_code == 302
    # ...pero ahora admin2 es el último y no puede ser degradado por nadie más
    with app.app_context():
        assert users.count_admins(get_db()) == 1
    assert _user(app, "admin2")["id"] == uid2


def test_delete_user(app, admin, tmp_path):
    client, token = admin
    uid = add_user(app, "ana")
    home = tmp_path / "data" / "homes" / "ana"
    home.mkdir(parents=True)
    (home / "dato.txt").write_text("x")
    resp = client.post(f"/admin/users/{U(uid)}/delete", data={"_csrf": token})
    assert resp.status_code == 302
    assert _user(app, "ana") is None
    assert (home / "dato.txt").exists()  # los archivos se conservan


def test_edit_unknown_user(admin):
    client, token = admin
    assert client.get("/admin/users/9999").status_code == 404
    assert client.post("/admin/users/9999/delete", data={"_csrf": token}).status_code == 404


# --------------------------------------------------------------------------- ajustes

def test_settings_sections_render(admin):
    client, _ = admin
    assert client.get("/admin/settings").location.endswith("/admin/settings/general")
    for section, text in (("general", "Idioma por defecto"), ("storage", "Plantilla de carpeta personal"),
                          ("permissions", "Permisos del rol"), ("auth", "Entra ID"),
                          ("security", "Minutos de bloqueo"), ("clients", "Permitir tokens de API personales"),
                          ("ips", "IPs bloqueadas"),
                          ("quotas", "Cuota de las carpetas personales (MB)"),
                          ("files", "Ocultos para todos"), ("audit_settings", "Conservar la auditoría (días)"),
                          ("auto_backups", "Copias que se conservan"), ("monitoring", "Publicar métricas para Prometheus"),
                          ("backups", "Copias y base de datos"),
                          ("sessions", "Sesiones y tokens"), ("system", "Arranque")):
        resp = client.get(f"/admin/settings/{section}")
        assert resp.status_code == 200 and text in resp.get_data(as_text=True), section
    assert client.get("/admin/settings/nada").status_code == 404
    # La antigua sección de carpetas compartidas ahora está en Acceso
    assert client.get("/admin/settings/shares").location.endswith("/admin/access/folders")
    assert client.get("/admin/settings/maintenance").location.endswith("/admin/settings/auto_backups")
    token = get_csrf(client, "/admin/settings/system")
    assert client.post("/admin/settings/system", data={"_csrf": token}).status_code == 405


@pytest.mark.parametrize("section", ["general", "storage", "quotas", "files", "permissions", "auth", "security",
                                     "clients", "network", "preview", "audit_settings", "auto_backups", "monitoring"])
def test_settings_roundtrip_unchanged(app, admin, section):
    from storageweb.settings import runtime_view
    from storageweb.web.context import runtime

    client, _ = admin
    with app.app_context():
        before = runtime_view(runtime().current(get_db()))
    resp = client.post(f"/admin/settings/{section}", data=settings_form(client, section))
    assert resp.status_code == 302, resp.get_data(as_text=True)
    with app.app_context():
        assert runtime_view(runtime().current(get_db())) == before   # guardar sin cambios no cambia nada


def test_settings_change_applies_immediately(app, admin, tmp_path):
    client, _ = admin
    (tmp_path / "equipo").mkdir()
    data = settings_form(client, "general")
    data["app_name"] = ["Mi Nube"]
    assert client.post("/admin/settings/general", data=data).status_code == 302
    data = page_form(client, "/admin/access/folders/new")
    data.update({"name": ["equipo"], "label": ["Equipo"], "path": [str(tmp_path / "equipo")],
                 "read_only": ["on"], "add_kind": ["all"], "add_ref": [""], "add_level": ["write"]})
    assert client.post("/admin/access/folders/new", data=data).status_code == 302
    html = client.get("/f/home/").get_data(as_text=True)
    assert "Mi Nube" in html and "Equipo" in html
    assert client.get("/f/equipo/").status_code == 200


def test_settings_permissions_affect_users(app, admin):
    client, _ = admin
    data = settings_form(client, "permissions")
    data.pop("perm_upload", None)
    assert client.post("/admin/settings/permissions", data=data).status_code == 302
    add_user(app, "ana")
    user_client = app.test_client()
    login(user_client, "ana")
    assert "Subir archivos" not in visible(user_client.get("/f/home/").get_data(as_text=True))
    tok = get_csrf(user_client, "/f/home/")
    assert user_client.post("/upload/home/", data={"_csrf": tok}).status_code == 403
    # el admin conserva todos los permisos
    assert "Subir archivos" in client.get("/f/home/").get_data(as_text=True)


def test_settings_invalid_shows_error_next_to_field(app, admin):
    client, _ = admin
    data = settings_form(client, "storage")
    data["home_template"] = ["/srv/sin-placeholder"]
    resp = client.post("/admin/settings/storage", data=data)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400 and "{username}" in html
    assert 'class="span2 has-error"' in html and 'class="field-error"' in html
    assert 'value="/srv/sin-placeholder"' in html                     # se conserva lo escrito
    assert settings_form(client, "storage")["home_template"][0] != "/srv/sin-placeholder"


def test_settings_cannot_disable_all_logins(app, admin):
    client, _ = admin
    data = settings_form(client, "auth")
    data.pop("local_enabled", None)
    resp = client.post("/admin/settings/auth", data=data)
    assert resp.status_code == 400 and "al menos un" in resp.get_data(as_text=True)


def test_settings_role_mappings(app, admin):
    from storageweb.web.context import settings

    client, _ = admin
    data = settings_form(client, "auth")
    data["entra_role_mappings"] = ["GrupoX = superadmin"]
    assert client.post("/admin/settings/auth", data=data).status_code == 400
    data["entra_role_mappings"] = ["sin igual"]
    assert client.post("/admin/settings/auth", data=data).status_code == 400
    data = settings_form(client, "auth")
    data.update({"mapping_group": ["StorageWeb.Admin", "lectores", ""], "mapping_role": ["admin", "user", "user"]})
    assert client.post("/admin/settings/auth", data=data).status_code == 302
    with app.test_request_context():
        assert settings()["auth"]["entra"]["role_mappings"] == {"storageweb.admin": "admin", "lectores": "user"}
    html = client.get("/admin/settings/auth").get_data(as_text=True)
    assert 'name="mapping_group" value="storageweb.admin"' in html


def test_secret_kept_when_blank_and_never_shown(app, admin):
    from storageweb.web.context import settings

    client, _ = admin
    data = settings_form(client, "auth")
    data.update({"entra_enabled": ["on"], "entra_tenant_id": ["t1"], "entra_client_id": ["c1"],
                 "entra_client_secret": ["muy-secreto"]})
    assert client.post("/admin/settings/auth", data=data).status_code == 302
    html = client.get("/admin/settings/auth").get_data(as_text=True)
    assert "muy-secreto" not in html and "configurado" in html

    data = settings_form(client, "auth")
    assert data["entra_client_secret"] == [""]
    data["entra_button_label"] = ["Entrar con Microsoft"]
    assert client.post("/admin/settings/auth", data=data).status_code == 302
    with app.test_request_context():
        assert settings()["auth"]["entra"]["client_secret"] == "muy-secreto"
    assert "Entrar con Microsoft" in app.test_client().get("/login").get_data(as_text=True)


def test_settings_origin_and_field_reset(app, make_app, admin):
    """Cada campo que no tiene su valor predeterminado se marca y se puede devolver a ese valor."""
    from storageweb.web.context import runtime, settings

    client, token = admin
    data = settings_form(client, "general")
    data["app_name"] = ["Desde la web"]
    client.post("/admin/settings/general", data=data)
    data = settings_form(client, "security")
    data["lockout_minutes"] = ["30"]
    client.post("/admin/settings/security", data=data)
    with app.app_context():
        saved = runtime().overrides(get_db())
        # (dependency_check_hours: el 0 que ponen los tests para no salir a internet, no es de este test)
        security = {k: v for k, v in saved["security"].items() if k != "dependency_check_hours"}
        assert saved["app_name"] == "Desde la web" and security == {"lockout_minutes": 30}
    html = client.get("/admin/settings/general").get_data(as_text=True)
    assert 'value="app_name"' in html and "Restablecer" in html and "modificado" in html
    assert "Volver al valor predeterminado: StorageWeb" in html
    html = client.get("/admin/settings/system").get_data(as_text=True)
    # Lista de Información: la etiqueta del campo y, al lado, su ruta
    assert "Nombre de la aplicación</a>" in html and "security.lockout_minutes</code>" in html

    resp = client.post("/admin/settings/reset-field", data={"_csrf": token, "path": "app_name"})
    assert resp.location.endswith("/admin/settings/general")
    with app.test_request_context():
        assert settings()["app_name"] == "StorageWeb" and settings()["security"]["lockout_minutes"] == 30
    assert "settings_field_reset" in client.get("/admin/audit").get_data(as_text=True)


def test_settings_reset(app, admin):
    client, token = admin
    data = settings_form(client, "general")
    data["app_name"] = ["Temporal"]
    client.post("/admin/settings/general", data=data)
    assert "Temporal" in client.get("/f/home/").get_data(as_text=True)
    client.post("/admin/settings/reset", data={"_csrf": token})
    assert "Temporal" not in client.get("/f/home/").get_data(as_text=True)


def test_settings_audited(app, admin):
    client, _ = admin
    client.post("/admin/settings/security", data=settings_form(client, "security"))
    html = client.get("/admin/audit?action=settings_updated").get_data(as_text=True)
    assert "settings_updated" in html and "root" in html and "security" in html


def test_audit_page_filters(app, admin):
    client, _ = admin
    login(app.test_client(), "nadie", "x")
    html = client.get("/admin/audit?action=login_failed").get_data(as_text=True)
    assert "nadie" in html
    html = client.get("/admin/audit?user=root").get_data(as_text=True)
    assert "nadie" not in html


def test_audit_pagination(app, admin):
    from storageweb.db.repositories import audit as audit_repo
    client, _ = admin
    with app.app_context():
        conn = get_db()
        for i in range(250):
            audit_repo.log(conn, "upload", f"home:/archivo-{i:03d}.txt", username="ana", ip="127.0.0.1")
    html = client.get("/admin/audit?user=ana").get_data(as_text=True)
    assert "archivo-249" in html and "archivo-150" in html and "archivo-149" not in html  # 100 por página
    assert "de 250" in html and "Página 1 de 3" in html
    html = client.get("/admin/audit?user=ana&page=3").get_data(as_text=True)
    assert "archivo-049" in html and "archivo-000" in html and "archivo-050" not in html
    assert "201–250 de 250" in html
    assert "user=ana" in html and "page=2" in html          # los enlaces conservan el filtro
    assert "archivo-000" in client.get("/admin/audit?user=ana&page=99").get_data(as_text=True)  # la última
    assert html.count('aria-label="Páginas"') == 2, "encima y debajo de la tabla"

    # Registros por página: los elegidos, y se mantienen al pasar de página
    html = client.get("/admin/audit?user=ana&per_page=25").get_data(as_text=True)
    assert "Página 1 de 10" in html and "archivo-225" in html and "archivo-224" not in html
    assert 'value="25" selected' in html and "per_page=25" in html and "page=2" in html
    assert "Página 1 de 3" in client.get("/admin/audit?user=ana&per_page=7").get_data(as_text=True)  # no válido: 100
    assert "Página 1 de 1" not in client.get("/admin/audit?user=ana&per_page=500").get_data(as_text=True)


# --------------------------------------------------------------------------- activar / desactivar

def _toggle(client, token, uid, enabled, **extra):
    return client.post(f"/admin/users/{U(uid)}/status", data={"_csrf": token, "enabled": "1" if enabled else "0", **extra})


@pytest.mark.parametrize("source", ["local", "entra", "pam"])
def test_disable_any_source(app, admin, source):
    client, token = admin
    uid = add_user(app, "persona", password=None if source != "local" else PASSWORD, source=source,
                   external_id="oid-x" if source == "entra" else None)
    resp = _toggle(client, token, uid, False)
    assert resp.status_code == 302 and resp.location.endswith(f"/admin/users/{U(uid)}")
    assert not _user(app, "persona")["enabled"]
    _toggle(client, token, uid, True)
    assert _user(app, "persona")["enabled"]


def test_disabled_sso_user_cannot_sign_in(entra_app, token_endpoint):
    """Una cuenta de Entra desactivada no entra aunque Microsoft la autentique."""
    from tests.sso_helpers import finish_login, start_login

    app = entra_app()
    admin_client = app.test_client()
    add_user(app, "root", role="admin")
    login(admin_client, "root")
    token = get_csrf(admin_client, "/f/home/")
    uid = add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-juan")
    _toggle(admin_client, token, uid, False)

    other = app.test_client()
    _, q = start_login(other, token_endpoint)
    assert "/login" in finish_login(other, q["state"]).location
    assert other.get("/f/home/").status_code == 302

    _toggle(admin_client, token, uid, True)
    _, q = start_login(other, token_endpoint)
    finish_login(other, q["state"])
    assert other.get("/f/home/").status_code == 200


def test_disable_ends_open_session(app, admin):
    client, token = admin
    uid = add_user(app, "ana")
    ana = app.test_client()
    login(ana, "ana")
    assert ana.get("/f/home/").status_code == 200
    _toggle(client, token, uid, False)
    assert ana.get("/f/home/").status_code == 302


def test_cannot_disable_self_or_last_admin(app, admin):
    client, token = admin
    me = _user(app, "root")
    _toggle(client, token, me["id"], False, next="/admin/users")
    html = client.get("/admin/users").get_data(as_text=True)
    assert "No puedes deshabilitar tu propia cuenta" in html and _user(app, "root")["enabled"]
    # otro admin no puede dejar el sistema sin administradores activos
    other = add_user(app, "jefa", role="admin")
    with app.app_context():
        users.update(get_db(), me["id"], enabled=True)
    _toggle(client, token, other, False)
    assert not _user(app, "jefa")["enabled"]


def test_disable_redirects_to_next_and_audits(app, admin):
    from storageweb.db.repositories import audit

    client, token = admin
    uid = add_user(app, "ana")
    resp = _toggle(client, token, uid, False, next="/admin/users?status=all")
    assert resp.location == "/admin/users?status=all"
    _toggle(client, token, uid, True)
    with app.app_context():
        actions = [r["action"] for r in audit.recent(get_db(), 5)]
    assert "user_disabled" in actions and "user_enabled" in actions


def test_users_status_filter(app, admin):
    client, token = admin
    uid = add_user(app, "inactivo")
    add_user(app, "activo")
    _toggle(client, token, uid, False)
    html = client.get("/admin/users?status=disabled").get_data(as_text=True)
    assert "inactivo" in html and ">activo<" not in html
    html = client.get("/admin/users?status=active").get_data(as_text=True)
    assert "inactivo" not in html and "activo" in html


def test_user_cannot_toggle(app, logged):
    client, token = logged
    uid = add_user(app, "otro")
    assert _toggle(client, token, uid, False).status_code == 403


def test_entra_delete_warning(app, admin):
    client, _ = admin
    uid = add_user(app, "juan@contoso.com", password=None, source="entra", external_id="o9")
    html = client.get(f"/admin/users/{U(uid)}").get_data(as_text=True)
    assert "se vuelve a crear" in html and "Desactivar usuario" in html


def test_change_password_page_never_links_outside(admin, app):
    client, _token = admin
    add_user(app, "luis")
    with app.app_context():
        uid = users.get_by_username(get_db(), "luis")["uid"]
    page = client.get(f"/admin/users/{uid}/password?next=https://evil.example/login").get_data(as_text=True)
    # «Volver» y «Cancelar» van a la ficha (la URL solo sale en el selector de idioma, que pasa por safe_next)
    assert 'href="https://evil.example' not in page
    assert page.count(f'href="/admin/users/{uid}"') >= 2
    page = client.get(f"/admin/users/{uid}/password?next=/admin/users?view=panels").get_data(as_text=True)
    assert 'href="/admin/users?view=panels"' in page

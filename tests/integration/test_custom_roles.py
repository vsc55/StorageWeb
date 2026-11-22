"""Acceso → Roles (core/roles.py, migración 007): roles propios con sus permisos, asignados a personas y a grupos."""
from __future__ import annotations

import subprocess
import sys

import pytest

from storageweb.core import accounts, roles
from storageweb.core import groups as group_core
from storageweb.core.permissions import permissions_for
from storageweb.db.repositories import groups as group_repo
from storageweb.db.repositories import users
from storageweb.web.context import get_db, settings
from tests.helpers import G, U, add_user, get_csrf, login


def _user(app, name):
    with app.app_context():
        return users.get_by_username(get_db(), name)


def test_create_edit_and_delete_a_role(app, admin):
    client, token = admin
    page = client.get("/admin/access/roles/list").get_data(as_text=True)
    assert "Nuevo rol" in page and "Usuario" in page and "Administrador" in page and "Sin permisos" in page
    resp = client.post("/admin/access/roles/new", data={"_csrf": token, "label": "Editores", "description": "Web",
                                                        "permissions": ["download", "upload", "edit"]})
    assert resp.status_code == 302 and resp.location.endswith("/admin/access/roles/list")    # a la lista
    assert "Editores" in client.get("/admin/access/roles/list").get_data(as_text=True)
    # En la vista Paneles: vuelve a ella, con el nuevo elegido
    assert "Editores" in client.get("/admin/access/roles/panel?r=editores").get_data(as_text=True)
    resp = client.post("/admin/access/roles/new", data={"_csrf": token, "label": "Revisores", "permissions": []})
    assert resp.location.endswith("/admin/access/roles/panel?r=revisores")
    assert client.get("/admin/access/roles/").location.endswith("/admin/access/roles/panel")
    client.get("/admin/access/roles/list")
    # Una clave que choca con una ruta se cambia
    resp = client.post("/admin/access/roles/new", data={"_csrf": token, "label": "New", "permissions": []})
    with app.app_context():
        assert "new-role" in settings()["roles"]
    with app.app_context():
        assert settings()["roles"]["editores"] == {"label": "Editores", "permissions": ["upload", "download", "edit"]}
    # Mismo nombre: no; uno de serie: no se toca
    assert client.post("/admin/access/roles/new", data={"_csrf": token, "label": "editores"}).status_code == 400
    assert client.post("/admin/access/roles/admin", data={"_csrf": token, "label": "X"}).status_code == 404
    assert client.post("/admin/access/roles/none", data={"_csrf": token, "label": "X"}).status_code == 404
    client.post("/admin/access/roles/editores", data={"_csrf": token, "label": "Editores web", "permissions": ["download"]})
    with app.app_context():
        assert settings()["roles"]["editores"]["permissions"] == ["download"]      # los ajustes, al día al momento
    # Borrarlo: sus personas se quedan sin permisos (nunca ganan permisos por borrar un rol)
    add_user(app, "ana", role="editores")
    resp = client.post("/admin/access/roles/editores/delete", data={"_csrf": token}, follow_redirects=True)
    assert "1 persona se queda sin permisos" in resp.get_data(as_text=True)
    assert _user(app, "ana")["role"] == "none"


def test_permissions_of_a_person_and_of_their_groups(app, admin):
    client, token = admin
    with app.app_context():
        roles.create(get_db(), "Lectores", permissions=["download"])
        roles.create(get_db(), "Borradores", permissions=["delete", "rename"])
    add_user(app, "ana", role="lectores")
    with app.app_context():
        ana = users.get_by_username(get_db(), "ana")
        assert permissions_for(ana, settings()) == {"download"}
        gid = group_core.create_group(get_db(), name="limpieza", label="Limpieza")
        group = group_repo.get_by_id(get_db(), gid)
        group_core.add_member(get_db(), group, ana)
        group_core.set_role(get_db(), group, "borradores")
    with app.app_context():                     # cada petición lee los ajustes (y los roles) de nuevo
        ana = users.get_by_username(get_db(), "ana")
        assert permissions_for(ana, settings()) == {"download", "delete", "rename"}   # el suyo más el del grupo
        with pytest.raises(group_core.GroupError, match="administradores"):
            group_core.set_role(get_db(), group_repo.get_by_id(get_db(), gid), "admin")
    # Desde la web: la ficha del grupo tiene su rol
    page = client.get(f"/admin/groups/{G(gid)}").get_data(as_text=True)
    assert 'name="role"' in page and "Borradores" in page and '<option value="admin"' not in page.split('name="role"')[1].split("</select>")[0]


def test_assign_a_role_to_a_person(app, admin):
    client, token = admin
    with app.app_context():
        roles.create(get_db(), "Lectores", permissions=["download"])
    add_user(app, "ana")
    ana = _user(app, "ana")
    page = client.get(f"/admin/users/{U(ana)}").get_data(as_text=True)
    assert '<option value="lectores"' in page
    client.post(f"/admin/users/{U(ana)}", data={"_csrf": token, "role": "lectores"})
    assert _user(app, "ana")["role"] == "lectores"
    assert "Lectores" in client.get("/admin/users").get_data(as_text=True)           # su nombre, no la clave
    with app.app_context():
        with pytest.raises(accounts.AccountError):
            accounts.set_role(get_db(), users.get_by_username(get_db(), "ana"), users.get_by_username(get_db(), "root"),
                              "no-existe")
    # En bloque
    client.post("/admin/users/bulk", data={"_csrf": token, "action": "role:user", "ids": [U(ana)]})
    assert _user(app, "ana")["role"] == "user"
    # Y lo que ve: con «lectores» no puede subir
    client.post(f"/admin/users/{U(ana)}", data={"_csrf": token, "role": "lectores"})
    ana_client = app.test_client()
    login(ana_client, "ana")
    page = ana_client.get("/f/home/").get_data(as_text=True)
    assert 'id="file-input"' not in page


def test_entra_mapping_can_give_a_role(app):
    with app.app_context():
        roles.create(get_db(), "Diseño", permissions=["download"])
    section = {"role_mappings": {"g-diseno": "diseno", "g-admins": "admin"}, "default_role": "user"}
    assert accounts.resolve_role(section, {"g-diseno"}) == "diseno"
    assert accounts.resolve_role(section, {"g-diseno", "g-admins"}) == "admin"
    assert accounts.resolve_role(section, set()) == "user"


def test_the_cli(app, write_config):
    from tests.integration.test_cli import ENV, ROOT
    cfg = write_config()
    def run(*args):
        return subprocess.run([sys.executable, "-m", "storageweb", "--config", str(cfg), *args],
                              capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=ENV)
    assert run("user-add", "ana", "--password", "contraseña-larga", "--role", "no-existe").returncode != 0
    assert run("user-add", "ana", "--password", "contraseña-larga").returncode == 0
    res = run("user-set", "ana", "--role", "tampoco")
    assert res.returncode != 0 and "no válido" in res.stderr



def test_role_of_new_accounts(app, admin):
    """Acceso → Roles: el rol de las cuentas nuevas (alta desde la web, CLI, importar, las que crea un método)."""
    client, token = admin
    with app.app_context():
        roles.create(get_db(), "Lectores", permissions=["download"])
    with app.app_context():
        assert settings()["permissions"]["default_role"] == "none"        # de serie: Sin permisos
    page = client.get("/admin/access/roles/list").get_data(as_text=True)
    assert "cuentas nuevas: Sin permisos" in page and "Usar «Lectores» para las cuentas nuevas" in page
    assert page.count('class="role-star is-on"') == 1                  # la estrella rellena, solo en el elegido
    assert client.post("/admin/access/roles/lectores/default", data={"_csrf": token}).status_code == 302
    assert '<option value="lectores" selected' in client.get("/admin/users/new").get_data(as_text=True)
    assert client.post("/admin/access/roles/no-existe/default", data={"_csrf": token}).status_code == 404
    # Administrador también (la página lo confirma antes) y Estado de la seguridad lo avisa
    assert "también las que se crean al entrar por primera vez" in page
    status = client.get("/admin/settings/security_status").get_data(as_text=True)
    assert "Las cuentas nuevas son administradoras" not in status
    assert client.post("/admin/access/roles/admin/default", data={"_csrf": token}).status_code == 302
    with app.app_context():
        assert settings()["permissions"]["default_role"] == "admin"
    status = client.get("/admin/settings/security_status").get_data(as_text=True)
    assert "Las cuentas nuevas son administradoras" in status
    # Entra ID con su «Rol de los usuarios nuevos» vacío: el de las cuentas nuevas
    assert accounts.resolve_role({"default_role": ""}, set(), fallback="lectores") == "lectores"
    assert accounts.resolve_role({"default_role": "user"}, set(), fallback="lectores") == "user"


def test_user_role_and_none(app, admin, write_config, make_app):
    """Usuario se edita en su ficha (sus permisos son permissions.user); Sin permisos no da nada; los permisos de
    Usuario fijados en config.json salen bloqueados y no cambian."""
    client, token = admin
    assert client.post("/admin/access/roles/user", data={"_csrf": token, "permissions": ["download"]}).status_code == 302
    with app.app_context():
        assert settings()["permissions"]["user"]["download"] and not settings()["permissions"]["user"]["upload"]
        assert permissions_for({"role": "none", "groups": "[]"}, settings()) == frozenset()
    panel = client.get("/admin/access/roles/panel?r=none").get_data(as_text=True)
    assert "Ningún permiso sobre los archivos" in panel
    # Con los permisos de Usuario en config.json (los tests ponen ahí upload…delete): bloqueados, no cambian
    from storageweb import create_app
    fixed = create_app(str(write_config()))
    fixed.testing = True
    add_user(fixed, "jefa", role="admin")
    root = fixed.test_client()
    login(root, "jefa")
    html = root.get("/admin/access/roles/user").get_data(as_text=True)
    assert 'value="upload" checked disabled' in html and 'value="share"  >' not in html and "bloqueado" in html
    tok = get_csrf(root, "/admin/access/roles/user")
    assert root.post("/admin/access/roles/user", data={"_csrf": tok, "permissions": ["share"]}).status_code == 302
    with fixed.app_context():
        user = settings()["permissions"]["user"]
        assert user["upload"] and user["delete"] and user["share"]


def test_panel_tabs_save_only_their_part(app, admin):
    """En Paneles cada pestaña envía solo lo suyo: General no toca los permisos y Permisos no toca el nombre."""
    client, token = admin
    client.post("/admin/access/roles/new", data={"_csrf": token, "label": "Editores", "description": "Web",
                                                 "permissions": ["download", "upload"]})
    page = client.get("/admin/access/roles/panel?r=editores").get_data(as_text=True)
    assert 'form="role-tab-form"' in page and "Quién lo tiene (0)" in page and "Permisos (2)" in page
    resp = client.post("/admin/access/roles/editores", data={"_csrf": token, "part": "general", "label": "Redactores",
                                                             "description": "", "next": "/admin/access/roles/panel?r=editores&tab=general"})
    assert resp.status_code == 302 and resp.location.endswith("tab=general")
    with app.app_context():
        role = settings()["roles"]["editores"]
        assert role["label"] == "Redactores" and set(role["permissions"]) == {"download", "upload"}
    client.post("/admin/access/roles/editores", data={"_csrf": token, "part": "permissions", "permissions": ["share"]})
    with app.app_context():
        role = settings()["roles"]["editores"]
        assert role["label"] == "Redactores" and role["permissions"] == ["share"]
    # Administrador y Sin permisos: sus permisos se ven, desactivados, sin botón de guardar
    page = client.get("/admin/access/roles/panel?r=admin&tab=permissions").get_data(as_text=True)
    assert 'value="upload" checked disabled' in page and 'form="role-tab-form"' not in page


def test_clone_role(app, admin):
    """Clonar: la ficha de Nuevo rol sale con lo del original y un nombre libre; Administrador no se clona."""
    client, token = admin
    client.post("/admin/access/roles/new", data={"_csrf": token, "label": "Editores", "description": "Web",
                                                 "permissions": ["download", "edit"]})
    assert 'href="/admin/access/roles/new?copy=editores"' in client.get("/admin/access/roles/list").get_data(as_text=True)
    page = client.get("/admin/access/roles/new?copy=editores").get_data(as_text=True)
    assert 'value="Editores (copia)"' in page and 'value="Web"' in page and "Una copia de «Editores»" in page
    assert 'value="edit" checked' in page and 'value="upload" checked' not in page
    client.post("/admin/access/roles/new", data={"_csrf": token, "label": "Editores (copia)", "permissions": ["edit"]})
    assert 'value="Editores (copia 2)"' in client.get("/admin/access/roles/new?copy=editores").get_data(as_text=True)
    # De serie: Usuario con sus permisos; Administrador y los que no existen, no
    page = client.get("/admin/access/roles/new?copy=user").get_data(as_text=True)
    assert 'value="Usuario (copia)"' in page and 'value="upload" checked' in page
    assert client.get("/admin/access/roles/new?copy=admin").status_code == 404
    assert client.get("/admin/access/roles/new?copy=no-existe").status_code == 404
    with app.app_context():
        assert settings()["roles"]["editores"]["label"] == "Editores"          # el original, igual
    # Clonar una copia no acumula «(copia) (copia)…»; nombres largos y claves que coinciden al cortarse (40)
    page = client.get("/admin/access/roles/new?copy=editores-copia").get_data(as_text=True)
    assert 'value="Editores (copia 2)"' in page
    with app.app_context():
        long = "hfd (copia) (copia) (copia) (copia) (copia) (copia) (copia)"
        first = roles.create(get_db(), long, permissions=["download"])
        assert roles.copy_of(get_db(), settings(), first)["label"] == "hfd (copia)"
        keys = [roles.create(get_db(), "x" * 38 + suffix) for suffix in ("a1", "a2", "a3")]
        assert len(set(keys)) == 3 and all(len(k) <= 40 for k in keys)         # misma clave cortada → -2, -3
        big = roles.create(get_db(), "y" * 80)
        assert len(roles.copy_of(get_db(), settings(), big)["label"]) <= 80

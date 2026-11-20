"""Administración por zonas: Resumen, submenú, buscador (Ctrl+K) y Acceso → Carpetas compartidas."""
from __future__ import annotations

import pytest

from storageweb.core.storage import available_roots
from storageweb.db.repositories import audit, users
from storageweb.web.context import get_db, settings
from tests.helpers import add_user, login, page_form, visible


@pytest.fixture
def app(make_app, tmp_path):
    (tmp_path / "sw").mkdir()
    return make_app({"storage": {"shares": [
        {"name": "software", "label": "Software", "path": str(tmp_path / "sw"), "users": ["ana"], "groups": ["it"]},
        {"name": "facturas", "label": "Facturas", "path": str(tmp_path / "no-existe"), "users": ["*"]}]}})


def test_overview_shows_alerts_and_zones(admin):
    client, _ = admin
    html = visible(client.get("/admin/").get_data(as_text=True))
    assert "Necesita tu atención · 1" in html and "La carpeta compartida «Facturas» no existe en el servidor" in html
    assert 'href="/admin/access/folders#share-facturas"' in html
    for zone in ("Personas", "Acceso", "Seguridad", "Sistema", "Lo que más se hace"):
        assert zone in html
    assert 'class="rail-badge"' in html  # el globo del Resumen en la barra lateral


def test_zone_subnav_and_page_kind(admin):
    client, _ = admin
    html = client.get("/admin/groups/list").get_data(as_text=True)
    # Zona Personas: Usuarios, Grupos y Sesiones; la página actual marcada
    assert 'href="/admin/users/"' in html and 'href="/admin/settings/sessions"' in html
    assert 'class="zone-link active" href="/admin/groups/"' in html
    html = client.get("/admin/settings/security").get_data(as_text=True)
    assert "Reglas de bloqueo" in html and "IPs bloqueadas" in html and "Configuración · se aplica al guardar" in html
    # Una página por tema: los tokens y WebDAV no están entre las reglas de bloqueo, sino en la suya
    assert 'name="api_tokens"' not in html and 'name="webdav"' not in html
    html = client.get("/admin/settings/clients").get_data(as_text=True)
    assert 'name="api_tokens"' in html and 'name="webdav_passwords"' in html and 'name="lockout_minutes"' not in html
    html = client.get("/admin/settings/ips").get_data(as_text=True)
    assert "Operación · se aplica al momento" in html
    # Acceso: la matriz de grupos cuenta como página de la zona
    html = client.get("/admin/groups/matrix").get_data(as_text=True)
    assert 'class="zone-link active" href="/admin/groups/matrix"' in html and "Carpetas compartidas" in html


def test_web_changes_badge_in_subnav(admin):
    client, _ = admin
    data = page_form(client, "/admin/settings/storage")
    data.pop("create_home", None)                      # Carpetas personales: no crearlas al entrar
    client.post("/admin/settings/storage", data=data)
    html = client.get("/admin/settings/permissions").get_data(as_text=True)
    assert 'id="f-permissions-user-upload"' in html  # ancla del buscador
    # Submenú: valores no predeterminados por página (los tests ponen rename y delete a True)
    assert "1 ajuste no tiene su valor predeterminado" in html and "2 ajustes no tienen su valor predeterminado" in html


def test_search_json(app, admin):
    client, _ = admin
    add_user(app, "eva", display_name="Eva Martín")
    data = client.get("/admin/search?format=json&q=copia").get_json()
    kinds = {(r["kind"], r["title"]) for r in data["results"]}
    assert ("action", "Hacer una copia ahora") in kinds
    setting = next(r for r in data["results"] if r["kind"] == "setting" and "automática" in r["title"])
    assert setting["url"] == "/admin/settings/auto_backups#f-maintenance-backup_interval_hours"
    assert setting["path"] == "Sistema → Copias automáticas"
    # Sin tildes ni mayúsculas, usuarios y carpetas
    titles = [r["title"] for r in client.get("/admin/search?format=json&q=MARTIN").get_json()["results"]]
    assert "Eva Martín" in titles
    results = client.get("/admin/search?format=json&q=factur").get_json()["results"]
    assert {"kind": "share", "url": "/admin/access/folders/facturas"}.items() <= results[0].items()
    # Los secretos nunca salen como valor
    secret = next(r for r in client.get("/admin/search?format=json&q=client secret").get_json()["results"]
                  if r["kind"] == "setting")
    assert secret["hint"] == ""


def test_search_page_without_js(admin):
    client, _ = admin
    html = client.get("/admin/search?q=proxy").get_data(as_text=True)
    assert "Red y HTTPS" in html and 'href="/admin/settings/network"' in html
    assert "Nada con «zzzz»." in client.get("/admin/search?q=zzzz").get_data(as_text=True)


def test_search_is_admin_only(app, logged):
    client, _ = logged
    assert client.get("/admin/search?format=json&q=a").status_code in (302, 403)
    assert 'id="admin-search"' not in client.get("/f/home/").get_data(as_text=True)


def test_folder_list_and_detail(admin):
    client, _ = admin
    html = visible(client.get("/admin/access/folders").get_data(as_text=True))
    assert "Software" in html and "Facturas" in html and "No existe en el servidor." in html
    html = client.get("/admin/access/folders/software").get_data(as_text=True)
    assert 'name="entry_ref" value="ana"' in html and 'name="entry_ref" value="it"' in html
    assert client.get("/admin/access/folders/nada").status_code == 404


def test_folder_access_levels(app, admin, tmp_path):
    client, _ = admin
    add_user(app, "ana")
    data = page_form(client, "/admin/access/folders/software")
    data["entry_level"] = ["read", "none"]          # ana solo lectura; se quita el grupo it
    data.update({"add_kind": ["group"], "add_ref": ["Fin"], "add_level": ["read"]})
    resp = client.post("/admin/access/folders/software", data=data)
    assert resp.status_code == 302 and resp.location.endswith("/admin/access/folders#share-software")
    with app.test_request_context():
        share = settings()["storage"]["shares"][0]
        assert share["users"] == ["ana"] and share["read_only_users"] == ["ana"]
        assert share["groups"] == ["fin"] and share["read_only_groups"] == ["fin"]
        ana = users.get_by_username(get_db(), "ana")
        root = next(r for r in available_roots(ana, settings()) if r["name"] == "software")
        assert root["read_only"] is True
        assert audit.recent(get_db(), 1)[0]["action"] == "share_updated"
    user = app.test_client()
    login(user, "ana")
    html = user.get("/f/software/").get_data(as_text=True)
    assert 'id="upload' not in html or "disabled" in html  # sin escritura no se puede subir


def test_folder_create_validate_and_delete(app, admin, tmp_path):
    client, _ = admin
    data = page_form(client, "/admin/access/folders/new")
    data.update({"name": ["home"], "label": ["Casa"], "path": [str(tmp_path)]})
    resp = client.post("/admin/access/folders/new", data=data)
    assert resp.status_code == 400 and "reservado" in resp.get_data(as_text=True)
    data.update({"name": ["equipo"], "add_kind": ["all"], "add_ref": [""], "add_level": ["read"]})
    assert client.post("/admin/access/folders/new", data=data).status_code == 302
    with app.test_request_context():
        new = settings()["storage"]["shares"][-1]
        assert new["name"] == "equipo" and new["users"] == ["*"] and new["read_only_users"] == ["*"]
    token = page_form(client, "/admin/access/folders/equipo")["_csrf"][0]
    assert client.post("/admin/access/folders/equipo/delete", data={"_csrf": token}).status_code == 302
    with app.test_request_context():
        assert [s["name"] for s in settings()["storage"]["shares"]] == ["software", "facturas"]
        assert audit.recent(get_db(), 1)[0]["action"] == "share_deleted"
    assert tmp_path.exists()  # los archivos no se tocan


def test_locked_settings_are_marked(make_app, write_config):
    """Los ajustes fijados en config.json o en el entorno: candado con cuántos en el menú de la zona y la lista
    arriba de la página, con enlace a cada uno."""
    import json
    import os
    from tests.helpers import add_user, login

    app = make_app()
    path = write_config({"storage": {"page_size": 300, "show_hidden": True}})   # config.json con dos ajustes fijos
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data), encoding="utf-8")
    os.environ["STORAGEWEB_STORAGE__MAX_FILE_SIZE_MB"] = "100"
    try:
        from storageweb import create_app
        app = create_app(str(path))
        app.testing = True
        add_user(app, "root", role="admin")
        client = app.test_client()
        login(client, "root")
        html = client.get("/admin/settings/files").get_data(as_text=True)
    finally:
        del os.environ["STORAGEWEB_STORAGE__MAX_FILE_SIZE_MB"]
    assert 'class="pill pill-lock"' in html and "3 ajustes están fijados en config.json o en el entorno" in html
    assert "3 ajustes de esta página están fijados fuera de la web" in html
    assert 'href="#f-storage-page_size"' in html and "STORAGEWEB_STORAGE__MAX_FILE_SIZE_MB" in html

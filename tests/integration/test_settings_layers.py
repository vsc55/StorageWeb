"""Capas de configuración en la web: predeterminado < web < config.json < entorno, bloqueos y perfiles."""
from __future__ import annotations

import pytest

from storageweb.web.context import get_db, runtime, settings
from tests.helpers import add_user, get_csrf, login, page_form


@pytest.fixture
def locked_app(monkeypatch, tmp_path):
    """App con app_name y las carpetas fijados en config.json y el Client ID en una variable de entorno."""
    import json

    from storageweb import create_app

    monkeypatch.setenv("STORAGEWEB_AUTH__ENTRA__CLIENT_ID", "id-del-entorno")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "data_dir": "data", "session": {"cookie_secure": False}, "server": {"behind_proxy": False},
        "app_name": "Del fichero",
        "storage": {"shares": [{"name": "fija", "label": "Fija", "path": str(tmp_path / "fija"), "users": ["*"]}]},
    }), encoding="utf-8")
    app = create_app(str(path))
    with app.app_context():  # los tests comprueban textos en español
        runtime().save(get_db(), {**runtime().current(get_db()), "default_locale": "es"}, "test")
    app.testing = True
    return app


def _admin(app):
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return client, get_csrf(client, "/admin/settings/general")


def test_locked_fields_are_shown_disabled(locked_app):
    client, _ = _admin(locked_app)
    html = client.get("/admin/settings/general").get_data(as_text=True)
    assert '<input data-field="app_name" disabled type="text" name="app_name"' in html and "config.json</span>" in html
    html = client.get("/admin/settings/auth").get_data(as_text=True)
    assert '<input data-field="auth.entra.client_id" disabled type="text" name="entra_client_id"' in html
    assert "STORAGEWEB_AUTH__ENTRA__CLIENT_ID" in html            # el título dice qué variable lo fija
    assert '<input data-field="auth.entra.tenant_id" type="text" name="entra_tenant_id"' in html  # lo demás, editable
    html = client.get("/admin/settings/system").get_data(as_text=True)
    assert "<code>STORAGEWEB_AUTH__ENTRA__CLIENT_ID</code>" in html and "Carpetas compartidas</a>" in html
    html = client.get("/admin/").get_data(as_text=True)
    assert "3 ajustes están bloqueados" in html


def test_saving_a_section_ignores_locked_fields(locked_app):
    client, _ = _admin(locked_app)
    data = page_form(client, "/admin/settings/general")
    data["primary_color"] = ["#112233"]
    data["custom_color"] = ["on"]
    assert client.post("/admin/settings/general", data=data).status_code == 302
    with locked_app.test_request_context():
        assert settings()["app_name"] == "Del fichero" and settings()["branding"]["primary_color"] == "#112233"
        assert "app_name" not in runtime().overrides(get_db())
    with locked_app.app_context():
        assert runtime().origins(get_db()) == {"app_name": "file", "storage.shares": "file",
                                               "auth.entra.client_id": "env", "default_locale": "web",
                                               "branding.primary_color": "web"}


def test_locked_field_cannot_be_reset(locked_app):
    client, token = _admin(locked_app)
    html = client.post("/admin/settings/reset-field", data={"_csrf": token, "path": "app_name"},
                       follow_redirects=True).get_data(as_text=True)
    with locked_app.test_request_context():
        assert settings()["app_name"] == "Del fichero"
    assert "Del fichero" in html


def test_locked_shares_are_read_only(locked_app):
    client, token = _admin(locked_app)
    html = client.get("/admin/access/folders").get_data(as_text=True)
    assert "«Carpetas compartidas» está fijado en config.json" in html and "Nueva carpeta compartida</a>" not in html
    html = client.get("/admin/access/folders/fija").get_data(as_text=True)
    assert '<fieldset class="plain-fieldset" disabled>' in html
    resp = client.post("/admin/access/folders/fija/delete", data={"_csrf": token}, follow_redirects=True)
    assert "no se puede cambiar desde la web" in resp.get_data(as_text=True)
    with locked_app.test_request_context():
        assert [s["name"] for s in settings()["storage"]["shares"]] == ["fija"]


def test_entra_flows_refuse_locked_fields(locked_app):
    client, token = _admin(locked_app)
    html = client.post("/admin/settings/entra/rotate", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "STORAGEWEB_AUTH__ENTRA__CLIENT_SECRET" not in html  # el secreto no está bloqueado…
    html = client.post("/admin/settings/entra/register", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "STORAGEWEB_AUTH__ENTRA__CLIENT_ID" in html          # …pero el registro escribiría el Client ID


def test_profiles_share_a_database(write_config, tmp_path):
    """Dos instancias con la misma base de datos y perfiles distintos tienen ajustes web distintos."""
    from storageweb import create_app

    db = str(tmp_path / "comun.db")
    apps = {}
    for profile in ("default", "oficina"):
        cfg_dir = tmp_path / profile
        cfg_dir.mkdir()
        path = write_config({"database": db, "settings_profile": profile})
        target = cfg_dir / "config.json"
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        apps[profile] = create_app(str(target))
        apps[profile].testing = True
    with apps["oficina"].app_context():
        view = {"app_name": "Oficina"}
        runtime().save(get_db(), {**runtime().current(get_db()), **view}, "test")
    with apps["oficina"].test_request_context():
        assert settings()["app_name"] == "Oficina"
    with apps["default"].test_request_context():
        assert settings()["app_name"] == "StorageWeb"
        rows = {r["key"] for r in get_db().execute("SELECT key FROM settings")}
        assert "runtime:oficina" in rows


def test_invalid_profile_name(write_config):
    from storageweb import create_app
    from storageweb.settings import ConfigError

    with pytest.raises(ConfigError, match="settings_profile"):
        create_app(str(write_config({"settings_profile": "con espacios"})))


def test_reset_button_carries_the_default_and_messages_use_labels(app, admin):
    client, token = admin
    data = page_form(client, "/admin/settings/storage")
    data.pop("create_shares", None)
    data["create_shares"] = ["on"]
    data["max_file_size_mb"] = ["50"]
    client.post("/admin/settings/storage", data=data)
    html = client.get("/admin/settings/storage").get_data(as_text=True)
    # El JavaScript pone estos valores en el formulario sin guardar (se aplican con «Guardar»)
    assert 'value="storage.create_shares"' in html and 'data-default="false"' in html
    assert 'value="storage.max_file_size_mb"' in html and 'data-default="0"' in html
    assert 'data-field="storage.create_shares"' in html
    # Sin JavaScript, el botón restablece en el servidor y el aviso nombra el campo por su etiqueta
    html = client.post("/admin/settings/reset-field", data={"_csrf": token, "path": "storage.create_shares"},
                       follow_redirects=True).get_data(as_text=True)
    assert "«Crear carpetas compartidas si no existen» vuelve a tener su valor predeterminado." in html
    html = client.get("/admin/settings/system").get_data(as_text=True)
    assert "Tamaño máximo por archivo (MB)" in html and "storage.max_file_size_mb" in html

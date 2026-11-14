"""Fixtures comunes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import add_user, deep_update, get_csrf, login


@pytest.fixture(autouse=True)
def spanish_locale():
    """Idioma activo fuera de las peticiones (core, CLI en proceso): español, como la configuración de los tests."""
    from storageweb import i18n

    token = i18n.set_locale("es")
    yield
    i18n.reset_locale(token)


@pytest.fixture
def write_config(tmp_path: Path):
    def _write(overrides: dict | None = None) -> Path:
        cfg = {
            "server": {"behind_proxy": False, "max_upload_mb": 5},
            "data_dir": "data",
            "session": {"cookie_secure": False},
            "storage": {"home_template": "data/homes/{username}"},
            # Los tests comprueban los textos en español: se fija explícitamente (por defecto es inglés)
            "default_locale": "es",
            # En los tests de archivos el rol user tiene todos los permisos; los valores por
            # defecto (sin renombrar/borrar) se prueban aparte
            "permissions": {"user": {p: True for p in ("upload", "download", "mkdir", "rename", "delete")}},
        }
        deep_update(cfg, overrides or {})
        path = tmp_path / "config.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path
    return _write


@pytest.fixture
def make_app(write_config):
    """App de prueba. Los ajustes editables van a la base de datos (como si los hubiera guardado un
    admin desde la web) y en config.json solo queda lo de arranque: así se pueden cambiar en los tests.
    Para probar campos bloqueados por config.json, escribe el fichero con ``write_config``."""
    def _make(overrides: dict | None = None):
        from storageweb import create_app
        from storageweb.db.repositories import settings as settings_repo
        from storageweb.settings import RUNTIME_KEY, runtime_part
        from storageweb.web.context import get_db

        path = write_config(overrides)
        data = json.loads(path.read_text(encoding="utf-8"))
        runtime = runtime_part(data)
        path.write_text(json.dumps({k: v for k, v in data.items() if k not in runtime}), encoding="utf-8")
        app = create_app(str(path))
        app.testing = True
        with app.app_context():
            settings_repo.put(get_db(), RUNTIME_KEY, runtime, "tests")
        return app
    return _make


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_conn(tmp_path):
    """Conexión SQLite con el esquema aplicado, sin Flask (tests unitarios)."""
    from storageweb.db import connect, migrate

    conn = connect(str(tmp_path / "unit.db"))
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def logged(app, client):
    """Cliente con el usuario 'ana' autenticado. Devuelve (client, csrf_token)."""
    add_user(app, "ana", display_name="Ana López")
    resp = login(client, "ana")
    assert resp.status_code == 302
    return client, get_csrf(client, "/f/home/")


@pytest.fixture
def admin(app, client):
    """Cliente con el administrador 'root' autenticado. Devuelve (client, csrf_token)."""
    add_user(app, "root", role="admin")
    assert login(client, "root").status_code == 302
    return client, get_csrf(client, "/f/home/")


@pytest.fixture
def home(tmp_path) -> Path:
    return tmp_path / "data" / "homes" / "ana"

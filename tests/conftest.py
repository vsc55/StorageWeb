"""Fixtures comunes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import deep_update, run_cli, signed_in


@pytest.fixture(autouse=True)
def spanish_locale():
    """Idioma activo fuera de las peticiones (core, CLI en proceso): español, como la configuración de los tests."""
    from storageweb import i18n

    token = i18n.set_locale("es")
    yield
    i18n.reset_locale(token)


@pytest.fixture(autouse=True)
def no_internet(monkeypatch):
    """Las consultas de core/advisories (PyPI, npm, OSV.dev) no salen nunca de los tests: contestan «inalcanzable»
    salvo que un test ponga sus respuestas (tests/unit/test_advisories.py)."""
    from storageweb.core import advisories
    monkeypatch.setattr(advisories, "_get_json", lambda url, timeout, data=None: {"ok": False, "error": "unreachable"})


@pytest.fixture
def fresh_ipban():
    """Sin las reglas de IP que core/ipban guarda en memoria de otro test (antes y después)."""
    from storageweb.core import ipban
    ipban.invalidate()
    yield
    ipban.invalidate()


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
            # La comprobación automática de vulnerabilidades sale a internet: en los tests, nunca sola
            "security": {"dependency_check_hours": 0},
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
        from storageweb.settings import runtime_part

        path = write_config(overrides)
        data = json.loads(path.read_text(encoding="utf-8"))
        runtime = runtime_part(data)
        path.write_text(json.dumps({k: v for k, v in data.items() if k not in runtime}), encoding="utf-8")
        app = create_app(str(path))
        app.testing = True
        from tests.helpers import APPS, store_settings
        store_settings(app, runtime)  # los ajustes a settings_values; carpetas, ubicaciones y cuotas, a sus tablas
        APPS.append(app)
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
    return signed_in(app, "ana", client=client, display_name="Ana López")


@pytest.fixture
def admin(app, client):
    """Cliente con el administrador 'root' autenticado. Devuelve (client, csrf_token)."""
    return signed_in(app, "root", client=client, role="admin")


@pytest.fixture
def cli(write_config):
    """La CLI en otro proceso con el config.json de los tests: ``cli("user-add", "ana", ...)``. Exige que acabe
    bien salvo ``ok=False``; el resto de argumentos van a :func:`tests.helpers.run_cli`."""
    cfg = write_config()

    def run(*args, ok=True, **kw):
        return run_cli(cfg, *args, ok=ok, **kw)
    return run


@pytest.fixture
def home(tmp_path) -> Path:
    return tmp_path / "data" / "homes" / "ana"

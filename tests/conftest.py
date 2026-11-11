from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "contraseña-segura"


def deep_update(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


@pytest.fixture
def write_config(tmp_path: Path):
    def _write(overrides: dict | None = None) -> Path:
        cfg = {
            "server": {"behind_proxy": False, "max_upload_mb": 5},
            "data_dir": "data",
            "session": {"cookie_secure": False},
            "storage": {"home_template": "data/homes/{username}"},
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
    def _make(overrides: dict | None = None):
        from src import create_app

        app = create_app(str(write_config(overrides)))
        app.testing = True
        return app
    return _make


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(app, username: str, password: str | None = PASSWORD, source: str = "local",
             role: str = "user", **kw) -> int:
    from src.db import users

    with app.app_context():
        return users.create(username=username, source=source, role=role,
                            password_hash=generate_password_hash(password) if password else None, **kw)


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match, "no se encontró el token CSRF en la página"
    return match.group(1)


def get_csrf(client, url: str = "/login") -> str:
    return csrf_from(client.get(url).get_data(as_text=True))


def login(client, username: str, password: str = PASSWORD, next_url: str = ""):
    token = get_csrf(client)
    return client.post("/login", data={"username": username, "password": password,
                                       "_csrf": token, "next": next_url})


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

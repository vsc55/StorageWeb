import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cli(write_config):
    cfg = write_config()

    def run(*args, ok=True):
        res = subprocess.run([sys.executable, str(ROOT / "manage.py"), "--config", str(cfg), *args],
                             capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                             env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        if ok:
            assert res.returncode == 0, res.stderr
        return res
    return run


def test_user_lifecycle(cli, make_app):
    cli("user-add", "ana", "--password", "contraseña-larga", "--name", "Ana", "--groups", "RRHH, IT")
    out = cli("user-list").stdout
    assert "ana" in out and "it,rrhh" in out and " user " in out

    assert cli("user-add", "ana", "--password", "contraseña-larga", ok=False).returncode != 0
    cli("user-set", "ana", "--disable")
    assert " no " in cli("user-list").stdout
    cli("user-set", "ana", "--enable", "--home", "/datos/ana")
    assert "/datos/ana" in cli("user-list").stdout
    cli("user-passwd", "ana", "--password", "otra-contraseña")
    cli("user-del", "ana")
    assert "ana" not in cli("user-list").stdout


def test_password_too_short(cli):
    res = cli("user-add", "ana", "--password", "corta", ok=False)
    assert res.returncode != 0 and "al menos" in res.stderr


def test_unknown_user(cli):
    assert cli("user-del", "nadie", ok=False).returncode != 0


def test_created_user_can_login(cli, write_config):
    from src import create_app

    from .conftest import login

    cli("user-add", "ana", "--password", "contraseña-larga")
    app = create_app(str(write_config()))
    client = app.test_client()
    assert login(client, "ana", "contraseña-larga").status_code == 302


def test_check_config_and_audit(cli):
    assert "Configuración válida" in cli("check-config").stdout
    cli("audit", "--limit", "5")


def test_bad_config(tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text("{malo", encoding="utf-8")
    res = subprocess.run([sys.executable, str(ROOT / "manage.py"), "--config", str(bad), "user-list"],
                         capture_output=True, text=True, cwd=ROOT)
    assert res.returncode != 0

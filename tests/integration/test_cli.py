import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Funciona tanto con el paquete instalado (pip install -e .) como sin instalar
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "STORAGEWEB_LANG": "es",
       "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "src"), os.environ.get("PYTHONPATH")]))}


@pytest.fixture
def cli(write_config):
    cfg = write_config()

    def run(*args, ok=True):
        res = subprocess.run([sys.executable, "-m", "storageweb", "--config", str(cfg), *args],
                             capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=ENV)
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
    from storageweb import create_app
    from tests.helpers import login

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
    res = subprocess.run([sys.executable, "-m", "storageweb", "--config", str(bad), "user-list"],
                         capture_output=True, text=True, cwd=ROOT, env=ENV)
    assert res.returncode != 0


def test_password_stdin_and_user_exists(cli, write_config):
    cfg = write_config()
    env_cmd = [sys.executable, "-m", "storageweb", "--config", str(cfg)]
    assert subprocess.run([*env_cmd, "user-exists", "eva"], cwd=ROOT, env=ENV).returncode == 1
    res = subprocess.run([*env_cmd, "user-add", "eva", "--role", "admin", "--password-stdin"],
                         input="contraseña-por-stdin\n", capture_output=True, text=True,
                         encoding="utf-8", cwd=ROOT, env=ENV)
    assert res.returncode == 0, res.stderr
    assert subprocess.run([*env_cmd, "user-exists", "eva"], cwd=ROOT, env=ENV).returncode == 0

    from storageweb import create_app
    from tests.helpers import login
    app = create_app(str(cfg))
    assert login(app.test_client(), "eva", "contraseña-por-stdin").status_code == 302


def test_backup_and_restore_cli(cli, write_config, tmp_path):
    cfg = write_config()
    cli("user-add", "ana", "--password", "contraseña-larga")
    out = cli("backup", "--output", str(tmp_path / "copias"), "--keep", "3").stdout.strip()
    assert out.endswith(".tar.gz") and Path(out).exists()
    assert "esquema" in cli("backup-list", "--output", str(tmp_path / "copias")).stdout
    cli("user-del", "ana")
    assert cli("restore", out, ok=False).returncode == 1  # sin --force no reemplaza
    assert "Restaurada" in cli("restore", out, "--force").stdout
    assert "ana" in cli("user-list").stdout
    audit_out = cli("audit", "--limit", "5").stdout
    assert "restore" in audit_out


def test_settings_reset_cli(cli, write_config):
    from storageweb import create_app
    from storageweb.web.context import get_db, runtime, settings

    cfg = write_config()
    app = create_app(str(cfg))
    with app.test_request_context():
        new = {"app_name": "Roto"}
        runtime().save(get_db(), new, "root")
    with app.test_request_context():
        assert settings()["app_name"] == "Roto"
    assert "descartados" in cli("settings-reset").stdout
    with app.test_request_context():
        assert settings()["app_name"] == "StorageWeb"

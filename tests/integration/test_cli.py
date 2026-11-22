# La CLI va en otro proceso (fixture ``cli`` de tests/conftest.py y tests.helpers.run_cli): funciona tanto con el
# paquete instalado (pip install -e .) como sin instalar
from pathlib import Path

from tests.helpers import run_cli


def test_user_lifecycle(cli, make_app):
    cli("user-add", "ana", "--password", "contraseña-larga", "--name", "Ana", "--groups", "RRHH, IT")
    out = cli("user-list").stdout
    assert "ana" in out and "it,rrhh" in out and " none " in out          # el rol de las cuentas nuevas

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
    assert run_cli(bad, "user-list").returncode != 0


def test_password_stdin_and_user_exists(cli, write_config):
    cfg = write_config()
    assert run_cli(cfg, "user-exists", "eva").returncode == 1
    run_cli(cfg, "user-add", "eva", "--role", "admin", "--password-stdin", input="contraseña-por-stdin\n", ok=True)
    assert run_cli(cfg, "user-exists", "eva").returncode == 0

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


def test_own_home_inside_the_allowed_folders(write_config, tmp_path):
    """``user-add --home`` y ``user-set --home`` miran ``storage.allowed_folders`` (Sistema → Carpetas del servidor)."""
    cfg = write_config({"storage": {"allowed_folders": [str(tmp_path / "data")]}})

    def run(*args):
        return run_cli(cfg, *args)
    fuera = str(tmp_path / "fuera" / "ana")
    res = run("user-add", "ana", "--password", "contraseña-larga", "--home", fuera)
    assert res.returncode != 0 and "permitidas" in res.stderr
    assert run("user-add", "ana", "--password", "contraseña-larga").returncode == 0
    res = run("user-set", "ana", "--home", fuera)
    assert res.returncode != 0 and "permitidas" in res.stderr
    assert run("user-set", "ana", "--home", str(tmp_path / "data" / "ana")).returncode == 0


def test_user_commands_go_through_the_core(cli):
    """Los comandos de usuarios hacen lo mismo que la web (core/accounts): cambiar la contraseña o desactivar cierran
    las sesiones y todo queda en la auditoría como «cli». Es la vía de rescate: deja quitar el rol al último
    administrador (en la web no se puede)."""
    cli("user-add", "jefa", "--password", "contraseña-larga", "--role", "admin")
    cli("user-set", "jefa", "--role", "user")                   # el último administrador: aquí sí
    assert " user " in cli("user-list").stdout
    cli("user-passwd", "jefa", "--password", "otra-contraseña")
    cli("user-set", "jefa", "--disable")
    cli("user-del", "jefa")
    log = cli("audit").stdout
    for action in ("user_created", "user_updated", "password_reset_by_admin", "user_disabled", "user_deleted"):
        assert action in log, action

"""Servicio de Windows (``cli/service.py`` y ``cli/service_host.py``): las órdenes que se registran y la parada
de Waitress desde otro hilo. Registrar el servicio de verdad necesita un Windows como administrador."""
from __future__ import annotations

import socket
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from storageweb.cli import service
from storageweb.cli.service_host import Runner


def test_command_line_runs_the_base_interpreter_without_its_site_packages():
    line = service.command_line("StorageWeb", Path(r"C:\Program Files\StorageWeb\config.json"),
                                Path(r"C:\Program Files\Python314\python.exe"),
                                [r"C:\Program Files\StorageWeb\venv\Lib\site-packages"])
    assert line.startswith('"C:\\Program Files\\Python314\\python.exe" -S -I ')
    assert "service_boot.py --name StorageWeb" in line
    assert '--config "C:\\Program Files\\StorageWeb\\config.json"' in line
    assert '--path "C:\\Program Files\\StorageWeb\\venv\\Lib\\site-packages"' in line


def test_site_paths_include_where_storageweb_is():
    import storageweb

    package_root = Path(storageweb.__file__).resolve().parents[1]
    assert any(package_root.is_relative_to(p) for p in service.site_paths())


def test_service_steps_use_the_virtual_account_unless_localsystem():
    steps = service.service_steps("StorageWeb", "virtual", "BIN")
    assert steps[0] == ["sc.exe", "create", "StorageWeb", "binPath=", "BIN", "start=", "delayed-auto",
                        "DisplayName=", "StorageWeb"]
    assert ["sc.exe", "config", "StorageWeb", "obj=", "NT SERVICE\\StorageWeb"] in steps
    assert ["sc.exe", "failure", "StorageWeb", "reset=", "86400", "actions=", service.FAILURE_ACTIONS] in steps
    assert ["sc.exe", "failureflag", "StorageWeb", "1"] in steps         # también si acaba con error
    assert not any(s[1] == "config" for s in service.service_steps("StorageWeb", "LocalSystem", "BIN"))


def test_grants_cover_python_data_homes_and_local_shares(tmp_path):
    cfg = {"data_dir": str(tmp_path / "data"),
           "storage": {"home_location": "", "home_template": str(tmp_path / "homes" / "{username}"),
                       "shares": [{"name": "equipo", "path": str(tmp_path / "equipo")},
                                  {"name": "nube", "location": "s3", "path": "equipo"}]}}
    python = tmp_path / "py" / "python.exe"
    got = service.grants(cfg, tmp_path / "config.json", python, [str(tmp_path / "venv"), str(tmp_path / "venv")])
    assert got == [(python.parent, "RX"), (tmp_path / "venv", "RX"), (tmp_path / "config.json", "R"),
                   (tmp_path / "data", "M"), (tmp_path / "homes", "M"), (tmp_path / "equipo", "M")]
    cfg["storage"]["home_location"] = "s3"                              # carpetas personales remotas
    assert (tmp_path / "homes", "M") not in service.grants(cfg, tmp_path / "config.json", python, [])


def test_icacls_inherits_on_folders_only():
    assert service.icacls("NT SERVICE\\StorageWeb", Path("D:/datos"), "M")[-1] == "NT SERVICE\\StorageWeb:(OI)(CI)M"
    assert service.icacls("NT SERVICE\\StorageWeb", Path("D:/config.json"), "R")[-1] == "NT SERVICE\\StorageWeb:R"


def test_home_base(tmp_path):
    assert service.home_base(str(tmp_path / "homes" / "{username}")) == tmp_path / "homes"
    assert service.home_base("{username}") is None


@pytest.mark.parametrize("label", ["STATE", "ESTADO"])
def test_parse_state(label):
    output = f"SERVICE_NAME: StorageWeb\n        TYPE               : 10  WIN32_OWN_PROCESS\n" \
             f"        {label}              : 4  RUNNING\n"
    assert service.parse_state(output) == "RUNNING"
    assert service.parse_state("nada") is None


def test_only_on_windows(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    assert service.cmd_service(type("A", (), {"action": "status", "name": "StorageWeb", "config": None})()) == 2
    assert "systemd" in capsys.readouterr().err


def test_runner_stops_from_another_thread_with_idle_connections_open(make_app):
    """La parada del servicio llega por otro hilo: debe cerrar también las conexiones keep-alive abiertas (si no,
    Waitress esperaría a que caduquen, 5 minutos) y terminar run()."""
    app = make_app()
    runner = Runner(app.config["SW"]["_config_path"], port=0)
    assert runner.start()
    port = runner.server.effective_port
    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=10) as resp:
        assert resp.status == 200
    idle = socket.create_connection(("127.0.0.1", port), timeout=10)  # una conexión que no pide nada
    try:
        runner.stop()
        thread.join(timeout=15)
        assert not thread.is_alive()
    finally:
        idle.close()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


def test_runner_stop_before_start_does_not_serve(make_app):
    app = make_app()
    runner = Runner(app.config["SW"]["_config_path"], port=0)
    runner.stop()
    assert runner.start() is False and runner.server is None

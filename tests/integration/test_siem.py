"""Reenvío de la auditoría a un SIEM (storageweb/siem.py, audit.*): syslog por UDP y TCP en los tres formatos,
fichero JSON por líneas, prueba desde la web, aviso si falla y validación de los ajustes."""
from __future__ import annotations

import json
import socket
import threading

import pytest

from storageweb import siem
from storageweb.core import alerts, maintenance
from storageweb.db.repositories import audit
from storageweb.settings import ConfigError, load_config
from storageweb.web.context import boot_config, get_db, settings
from tests.helpers import add_user, get_csrf, login


@pytest.fixture(autouse=True)
def fresh_forwarder(monkeypatch):
    """Cada test con su propio reenviador (el del proceso es global)."""
    forwarder = siem.Forwarder()
    monkeypatch.setattr(siem, "FORWARDER", forwarder)
    monkeypatch.setattr(siem, "configure", forwarder.configure)
    monkeypatch.setattr(siem, "emit", forwarder.emit)
    yield forwarder
    forwarder.configure({})


@pytest.fixture
def udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(5)
    yield sock
    sock.close()


def _admin(make_app, audit_cfg):
    app = make_app({"audit": audit_cfg})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return app, client


def test_formats():
    event = siem.event_of("2026-11-20T10:00:00+00:00", "ana", "login_failed", "home:/a|b", "192.0.2.1", 'x"]=')
    rfc = siem.format_syslog(event, "rfc5424", "local0", "srv")
    assert rfc.startswith("<132>1 2026-11-20T10:00:00+00:00 srv storageweb ")      # local0 (16) * 8 + warning (4)
    assert (' login_failed [storageweb@32473 level="warning" user="ana" ip="192.0.2.1" target="home:/a|b" '
            'detail="x\\"\\]="]') in rfc
    as_json = siem.format_syslog(event, "json", "auth", "srv")
    assert as_json.startswith("<36>1 ") and json.loads(as_json.split(" - ", 1)[1])["action"] == "login_failed"
    cef = siem.format_syslog({**event, "action": "upload", "level": "info"}, "cef", "local0", "srv")
    assert cef.startswith("<134>1 ") and "CEF:0|StorageWeb|StorageWeb|" in cef and "|upload|upload|3|" in cef
    assert "fname=home:/a|b" in cef and "msg=x\"]\\=" in cef


def test_udp_and_file_from_the_web(make_app, udp, tmp_path):
    port = udp.getsockname()[1]
    out = tmp_path / "audit.jsonl"
    app, client = _admin(make_app, {"syslog": f"udp://127.0.0.1:{port}", "syslog_format": "json",
                                    "file": str(out)})
    siem.FORWARDER.flush()                                        # el inicio de sesión de _admin ya se auditó
    received = []
    while True:
        try:
            received.append(json.loads(udp.recv(65535).decode().split(" - ", 1)[1]))
        except socket.timeout:
            break
        if any(e["action"] == "login" for e in received):
            break
    assert any(e["action"] == "login" and e["user"] == "root" for e in received)
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert any(e["action"] == "login" for e in lines) and siem.FORWARDER.status()["sent"] >= 1


def test_tcp_lines_and_test_button(make_app):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(5)
    chunks: list[bytes] = []

    def read(conn):
        conn.settimeout(5)
        try:
            while data := conn.recv(65535):
                chunks.append(data)
        except OSError:
            pass
        conn.close()

    def accept():      # la cola usa una conexión y la prueba otra
        for _ in range(2):
            try:
                conn, _addr = server.accept()
            except OSError:
                return
            threading.Thread(target=read, args=(conn,), daemon=True).start()
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    app, client = _admin(make_app, {"syslog": f"tcp://127.0.0.1:{server.getsockname()[1]}"})
    page = client.post("/admin/settings/maintenance/audit-forward/test",
                       data={"_csrf": get_csrf(client, "/admin/settings/audit_settings")}, follow_redirects=True)
    siem.FORWARDER.flush()
    t.join(5)
    assert "Evento de prueba enviado" in page.get_data(as_text=True)
    lines = b"".join(chunks).decode().splitlines()               # un mensaje por línea: el login y la prueba
    test = next(line for line in lines if " audit_forward_test " in line)
    assert test.startswith("<134>1 ") and any(" login " in line for line in lines)
    server.close()
    with app.app_context():
        assert audit.recent(get_db(), 5, action="audit_forward_test")[0]["detail"] == "ok"


def test_failure_is_shown_and_alerts(make_app):
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()                                                # nadie escucha: conexión rechazada
    app, client = _admin(make_app, {"syslog": f"tcp://127.0.0.1:{port}"})
    siem.FORWARDER.flush(timeout=20)          # el login ya se intentó enviar (en Windows, rechazar tarda ~2 s)
    assert siem.FORWARDER.status()["failing"]
    page = client.get("/admin/settings/audit_settings").get_data(as_text=True)
    assert "No llega:" in page
    with app.app_context():
        found = alerts.collect(settings(), boot_config(), maintenance.state(get_db()))
    assert any(a["key"] == "audit_forward_failing" for a in found)
    bad = client.post("/admin/settings/maintenance/audit-forward/test",
                      data={"_csrf": get_csrf(client, "/admin/settings/audit_settings")}, follow_redirects=True)
    assert "No se ha podido enviar el evento de prueba" in bad.get_data(as_text=True)


def test_full_queue_drops_without_blocking(monkeypatch):
    forwarder = siem.FORWARDER
    monkeypatch.setattr(siem, "QUEUE_SIZE", 2)
    forwarder._queue = siem.queue.Queue(maxsize=2)                 # noqa: SLF001
    forwarder._options = {"file": "x"}                            # noqa: SLF001 (activo, sin hilo que vacíe)
    for _ in range(5):
        forwarder.emit({"action": "x"})
    assert forwarder.dropped == 3
    forwarder._options = {}                                       # noqa: SLF001


def test_settings_are_validated(tmp_path):
    def load(fwd):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"audit": fwd}), encoding="utf-8")
        return load_config(p)
    assert load({})["audit"]["syslog"] == ""
    assert load({"file": "audit.jsonl"})["audit"]["file"] == str(tmp_path / "audit.jsonl")
    for bad, field in (({"syslog": "http://siem"}, "audit.syslog"), ({"syslog": "udp://"}, "audit.syslog"),
                       ({"syslog_format": "xml"}, "syslog_format"), ({"syslog_facility": "kern"}, "syslog_facility")):
        with pytest.raises(ConfigError, match=field):
            load(bad)

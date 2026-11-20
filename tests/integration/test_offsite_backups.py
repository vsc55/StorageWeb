"""Copias de seguridad fuera del servidor (maintenance.offsite_*, core/offsite.py): se envían a una ubicación al
hacerlas (web, automática y CLI), se rotan allí, avisan si fallan y se traen a otro servidor para restaurarlas."""
from __future__ import annotations

import pytest

from storageweb.cli import main as cli_main
from storageweb.core import alerts, backends, maintenance, offsite
from storageweb.db.repositories import audit
from storageweb.settings import ConfigError, load_config
from storageweb.web.context import boot_config, get_db, settings
from tests.fakes import FakeS3
from tests.helpers import add_user, get_csrf, login

BACKUPS = "/admin/settings/backups"
S3 = {"name": "copias", "label": "Copias", "type": "s3", "bucket": "bucket", "prefix": "",
      "access_key": "AK", "secret_key": "SECRETO"}


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "s3", lambda loc: fake)
    backends.clear_clients()
    yield fake
    backends.clear_clients()


@pytest.fixture
def admin_app(make_app, s3):
    app = make_app({"storage": {"locations": [S3]},
                    "maintenance": {"offsite_location": "copias", "offsite_path": "sw/copias", "offsite_keep": 2}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return app, client


def _remote(s3) -> list[str]:
    return sorted(k for k in s3.objects if k.startswith("sw/copias/") and not k.endswith("/"))   # sin el marcador de carpeta


def _create(client):
    return client.post("/admin/settings/maintenance/backups", data={"_csrf": get_csrf(client, BACKUPS)},
                       follow_redirects=True).get_data(as_text=True)


def test_web_backup_is_sent_and_rotated(admin_app, s3):
    app, client = admin_app
    page = _create(client)
    assert "También se ha enviado a" in page
    [key] = _remote(s3)
    with app.app_context():
        local = maintenance.list_backups(boot_config())[0]["name"]
        assert key == f"sw/copias/{local}"
        assert s3.objects[key][0] == (maintenance.backup_dir(boot_config()) / local).read_bytes()
        state = maintenance.state(get_db())["offsite"]
        assert state["ok"] and state["name"] == local
        assert audit.recent(get_db(), 5, action="backup_offsite")[0]["target"] == local
    for _ in range(3):
        s3.objects[f"sw/copias/storageweb-backup-2020010{_}-000000.tar.gz"] = (b"viejo", s3.objects[key][1].replace(year=2020))
    s3.objects["sw/copias/storageweb-backup-subida-a.tar.gz"] = (b"a mano", s3.objects[key][1].replace(year=2019))
    _create(client)
    names = [k.rsplit("/", 1)[1] for k in _remote(s3)]
    assert "storageweb-backup-subida-a.tar.gz" in names                         # las subidas a mano no rotan
    assert len([n for n in names if n[len("storageweb-backup-"):][0].isdigit()]) == 2   # offsite_keep


def test_failure_is_reported_and_alerts(admin_app, s3, monkeypatch):
    app, client = admin_app

    def broken(*_a, **_k):
        raise RuntimeError("sin red")
    monkeypatch.setattr(s3, "upload_file", broken)
    page = _create(client)
    assert "No se ha podido enviar fuera del servidor" in page and "sin red" in page
    with app.app_context():
        assert maintenance.list_backups(boot_config())               # la del servidor sí se hizo
        assert maintenance.state(get_db())["offsite"]["ok"] is False
        found = alerts.collect(settings(), boot_config(), maintenance.state(get_db()))
    assert any(a["key"] == "offsite_failed" for a in found)
    monkeypatch.undo()
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "s3", lambda loc: s3)
    with app.app_context():
        name = maintenance.list_backups(boot_config())[0]["name"]
    client.post(f"/admin/settings/maintenance/backups/{name}/offsite", data={"_csrf": get_csrf(client, BACKUPS)})
    assert _remote(s3) == [f"sw/copias/{name}"]


def test_list_and_bring_back_to_another_server(admin_app, s3, make_app):
    app, client = admin_app
    _create(client)
    with app.app_context():
        name = maintenance.list_backups(boot_config())[0]["name"]
    other = make_app({"data_dir": "otro", "storage": {"locations": [S3]},
                      "maintenance": {"offsite_location": "copias", "offsite_path": "sw/copias"}})
    add_user(other, "root2", role="admin")
    c2 = other.test_client()
    login(c2, "root2")
    with other.app_context():
        assert maintenance.list_backups(boot_config()) == []          # otro servidor: sin copias propias
    page = c2.get(BACKUPS + "?remote=1").get_data(as_text=True)
    assert name in page and "Traer a este servidor" in page
    assert name not in c2.get(BACKUPS).get_data(as_text=True).split('id="offsite"')[0]
    c2.post("/admin/settings/maintenance/backups/offsite/fetch", data={"_csrf": get_csrf(c2, BACKUPS), "name": name})
    with other.app_context():
        assert name in [b["name"] for b in maintenance.list_backups(boot_config())]
    bad = c2.post("/admin/settings/maintenance/backups/offsite/fetch",
                  data={"_csrf": get_csrf(c2, BACKUPS), "name": "../../config.json"}, follow_redirects=True)
    assert "no existe" in bad.get_data(as_text=True)


def test_cli_backup_sends_it_too(admin_app, s3, tmp_path, capsys):
    """El timer de systemd usa la CLI: la ubicación elegida desde la web (en la base de datos) también vale."""
    app, _client = admin_app
    cli_main(["--config", str(tmp_path / "config.json"), "backup"])
    created = capsys.readouterr().out.strip().splitlines()[-1]
    assert _remote(s3) == [f"sw/copias/{created.replace(chr(92), '/').rsplit('/', 1)[1]}"]
    with app.app_context():
        assert audit.recent(get_db(), 5, action="backup_offsite")[0]["username"] == "cli"
    cli_main(["--config", str(tmp_path / "config.json"), "backup", "--no-offsite"])
    assert len(_remote(s3)) == 1


def test_settings_are_validated(tmp_path):
    import json

    def load(maint, locations=()):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"storage": {"locations": list(locations)}, "maintenance": maint}), encoding="utf-8")
        return load_config(p)
    assert load({})["maintenance"]["offsite_location"] == ""
    with pytest.raises(ConfigError, match="offsite_location"):
        load({"offsite_location": "nada"})
    with pytest.raises(ConfigError, match="offsite_path"):
        load({"offsite_location": "copias", "offsite_path": "../fuera"}, [S3])

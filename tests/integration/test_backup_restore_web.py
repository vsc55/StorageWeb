"""Restaurar una copia de seguridad desde la web (con el servicio en marcha) y subir copias."""
import io
import json
import tarfile
from pathlib import Path

import pytest

from storageweb.core import backup, maintenance
from storageweb.db.repositories import audit, users
from storageweb.web.context import boot_config, get_db, settings
from tests.helpers import add_user, get_csrf, login, update_settings

BACKUPS = "/admin/settings/backups"


@pytest.fixture
def admin_app(make_app):
    app = make_app({"app_name": "Antes"})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return app, client


def _create(app, client) -> str:
    client.post("/admin/settings/maintenance/backups", data={"_csrf": get_csrf(client, BACKUPS)})
    with app.app_context():
        return maintenance.list_backups(boot_config())[0]["name"]


def _restore(client, name, word="RESTAURAR"):
    url = f"/admin/settings/maintenance/backups/{name}/restore"
    return client.post(url, data={"_csrf": get_csrf(client, url), "confirm": word})


def _names(app):
    with app.app_context():
        return [b["name"] for b in maintenance.list_backups(boot_config())]


def test_restore_brings_back_the_database_and_keeps_a_safety_copy(admin_app):
    app, client = admin_app
    name = _create(app, client)
    add_user(app, "nuevo")                                                   # cambios después de la copia
    other = app.test_client()
    login(other, "nuevo")
    update_settings(app, app_name="Después")

    page = client.get(f"/admin/settings/maintenance/backups/{name}/restore").get_data(as_text=True)
    assert "Escribe RESTAURAR para confirmar" in page and "Se hace antes una copia" in page
    resp = _restore(client, name, word="otra cosa")                         # sin la palabra, nada
    with app.app_context():
        assert users.get_by_username(get_db(), "nuevo") is not None

    resp = _restore(client, name)
    assert resp.status_code == 302 and resp.location.endswith(BACKUPS)       # quien restaura sigue dentro
    with app.app_context():
        assert users.get_by_username(get_db(), "nuevo") is None             # vuelve como estaba
        assert settings()["app_name"] == "Antes"
        actions = [(r["action"], r["target"]) for r in audit.recent(get_db(), 5)]
    assert ("backup_restored", name) in actions
    assert "copia anterior se ha guardado como" in client.get(BACKUPS).get_data(as_text=True)
    assert other.get("/f/home/").status_code == 302                          # el resto, fuera
    safety = [n for n in _names(app) if "antes-de-restaurar" in n]
    assert len(safety) == 1                                                  # para volver atrás
    resp = _restore(client, safety[0])
    with app.app_context():
        assert users.get_by_username(get_db(), "nuevo") is not None         # y se puede deshacer


def test_restorer_not_in_the_backup_is_signed_out(make_app):
    app = make_app()
    add_user(app, "otro", role="admin")
    first = app.test_client()
    login(first, "otro")
    name = _create(app, first)
    add_user(app, "root", role="admin")                                      # «root» no está en la copia
    client = app.test_client()
    login(client, "root")
    resp = _restore(client, name)
    assert resp.status_code == 302 and "/login" in resp.location
    assert "restaurada" in client.get(resp.location).get_data(as_text=True)
    assert client.get("/admin/").status_code == 302


def test_maintenance_answers_503_while_restoring(admin_app):
    app, client = admin_app
    maintenance.RESTORING.set()
    try:
        resp = app.test_client().get("/login")
        assert resp.status_code == 503 and resp.headers["Retry-After"] == "30"
        assert "Se está restaurando una copia" in resp.get_data(as_text=True)
        assert app.test_client().get("/static/css/base.css").status_code == 200
    finally:
        maintenance.RESTORING.clear()
    assert app.test_client().get("/login").status_code == 200


def _tar(manifest: dict, db: bytes = b"") -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for member, data in (("manifest.json", json.dumps(manifest).encode()), ("storageweb.db", db)):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_upload_a_backup_and_refuse_newer_or_invalid_ones(admin_app):
    app, client = admin_app
    name = _create(app, client)
    with app.app_context():
        data = (Path(boot_config()["data_dir"]) / "backups" / name).read_bytes()
    token = get_csrf(client, BACKUPS)
    resp = client.post("/admin/settings/maintenance/backups/upload", content_type="multipart/form-data",
                       data={"_csrf": token, "backup": (io.BytesIO(data), "copia-de-otro-servidor.tar.gz")})
    uploaded = [n for n in _names(app) if n.startswith("storageweb-backup-subida-")]
    assert resp.status_code == 302 and len(uploaded) == 1
    html = client.get(BACKUPS).get_data(as_text=True)
    assert "subida" in html and f"/maintenance/backups/{uploaded[0]}/restore" in html

    client.post("/admin/settings/maintenance/backups/upload", content_type="multipart/form-data",
                data={"_csrf": token, "backup": (io.BytesIO(b"no es una copia"), "x.tar.gz")})
    assert "no es una copia válida" in client.get(BACKUPS).get_data(as_text=True)
    assert len(_names(app)) == 2

    newer = _tar({"format": backup.FORMAT, "schema_version": 999, "created_at": "2030-01-01T00:00:00+00:00",
                  "storageweb_version": "9.0"})
    client.post("/admin/settings/maintenance/backups/upload", content_type="multipart/form-data",
                data={"_csrf": token, "backup": (io.BytesIO(newer), "storageweb-backup-20300101-000000.tar.gz")})
    assert "más nueva: actualiza antes de restaurar" in client.get(BACKUPS).get_data(as_text=True)


def test_rotation_only_removes_dated_backups(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for n, name in enumerate(["storageweb-backup-20260101-000000.tar.gz", "storageweb-backup-antes-de-restaurar-x.tar.gz",
                              "storageweb-backup-20260102-000000.tar.gz", "storageweb-backup-subida-y.tar.gz",
                              "storageweb-backup-20260103-000000.tar.gz"]):
        (folder / name).write_bytes(b"x")
    removed = backup.prune(folder, 1)
    assert sorted(p.name for p in removed) == ["storageweb-backup-20260101-000000.tar.gz",
                                               "storageweb-backup-20260102-000000.tar.gz"]
    assert sorted(p.name for p in folder.iterdir()) == ["storageweb-backup-20260103-000000.tar.gz",
                                                        "storageweb-backup-antes-de-restaurar-x.tar.gz",
                                                        "storageweb-backup-subida-y.tar.gz"]

"""Copias de seguridad y restauración (sin Flask)."""
from __future__ import annotations

import io
import json
import os
import tarfile
import time

import pytest

from storageweb.core import backup
from storageweb.db import connect, init_db
from storageweb.db.repositories import users
from storageweb.settings import ensure_secret_key, load_config


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"data_dir": "data", "storage": {"home_template": "h/{username}"}}),
                    encoding="utf-8")
    cfg = load_config(path)
    init_db(cfg["database"])
    ensure_secret_key(cfg)
    conn = connect(cfg["database"])
    users.create(conn, username="ana", source="local", role="admin")
    conn.close()
    return cfg


def _users(cfg):
    conn = connect(cfg["database"])
    try:
        return [r["username"] for r in users.list_all(conn)]
    finally:
        conn.close()


def test_create_contents(cfg, tmp_path):
    path = backup.create(cfg, tmp_path / "copias")
    assert path.name.startswith(backup.PREFIX) and path.name.endswith(backup.SUFFIX)
    with tarfile.open(path) as tar:
        assert set(tar.getnames()) == {"manifest.json", "storageweb.db", "config.json", "secret_key"}
    manifest = backup.read_manifest(path)
    assert manifest["format"] == 1 and manifest["schema_version"] >= 1
    if os.name != "nt":
        assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_backup_while_db_in_use(cfg, tmp_path):
    """La API de backup de SQLite da una copia consistente aunque haya una conexión abierta."""
    conn = connect(cfg["database"])
    users.create(conn, username="beto", source="local")
    path = backup.create(cfg, tmp_path / "copias")
    conn.close()
    restored = dict(cfg, database=str(tmp_path / "otra.db"))
    backup.restore(restored, path)
    assert _users(restored) == ["ana", "beto"]


def test_restore_roundtrip(cfg, tmp_path):
    path = backup.create(cfg, tmp_path / "copias")
    conn = connect(cfg["database"])
    users.create(conn, username="intruso", source="local")
    conn.close()

    with pytest.raises(backup.BackupError, match="--force"):
        backup.restore(cfg, path)
    manifest = backup.restore(cfg, path, force=True, config_to=tmp_path / "config.restaurado.json")
    assert _users(cfg) == ["ana"]
    assert manifest["restored_schema_version"] >= manifest["schema_version"]
    previous = list((tmp_path / "data").glob("storageweb.db.antes-de-restaurar-*"))
    assert len(previous) == 1
    assert (tmp_path / "config.restaurado.json").read_text(encoding="utf-8").startswith("{")


def test_restore_removes_stale_wal(cfg, tmp_path):
    path = backup.create(cfg, tmp_path / "copias")
    wal = tmp_path / "data" / "storageweb.db-wal"
    wal.write_bytes(b"basura")
    backup.restore(cfg, path, force=True)
    assert _users(cfg) == ["ana"]


def test_restore_secret_key(cfg, tmp_path):
    path = backup.create(cfg, tmp_path / "copias")
    key_file = tmp_path / "data" / "secret_key"
    original = key_file.read_text()
    key_file.unlink()
    backup.restore(cfg, path, force=True)
    assert key_file.read_text() == original


def test_keep_prunes_old(cfg, tmp_path):
    out = tmp_path / "copias"
    made = []
    for _ in range(4):
        made.append(backup.create(cfg, out, keep=2))
        time.sleep(0.01)
    assert backup.list_backups(out) == sorted(made)[-2:]


def _tar(path, members: dict, manifest: dict | None = None):
    with tarfile.open(path, "w:gz") as tar:
        if manifest is not None:
            members = {"manifest.json": json.dumps(manifest).encode(), **members}
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize("members, manifest", [
    ({"storageweb.db": b"x", "../escape": b"x"}, {"format": 1}),       # ruta peligrosa
    ({"storageweb.db": b"x"}, None),                                   # sin manifest
    ({"config.json": b"{}"}, {"format": 1}),                           # sin base de datos
    ({"storageweb.db": b"x"}, {"format": 99}),                         # formato desconocido
])
def test_rejects_invalid_archives(cfg, tmp_path, members, manifest):
    bad = tmp_path / "mala.tar.gz"
    _tar(bad, members, manifest)
    with pytest.raises(backup.BackupError):
        backup.restore(cfg, bad, force=True)
    assert _users(cfg) == ["ana"]  # la base de datos no se ha tocado


def test_rejects_newer_schema(cfg, tmp_path):
    bad = tmp_path / "futura.tar.gz"
    _tar(bad, {"storageweb.db": b"x"}, {"format": 1, "schema_version": 999})
    with pytest.raises(backup.BackupError, match="más nueva"):
        backup.restore(cfg, bad, force=True)


def test_not_a_tarball(cfg, tmp_path):
    bad = tmp_path / "nada.tar.gz"
    bad.write_bytes(b"no soy un tar")
    with pytest.raises(backup.BackupError):
        backup.read_manifest(bad)


def test_missing_database(tmp_path):
    cfg = load_config(tmp_path / "no-existe.json")
    with pytest.raises(backup.BackupError, match="No existe"):
        backup.create(cfg, tmp_path / "copias")

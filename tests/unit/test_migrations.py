"""Migraciones versionadas de la base de datos."""
import sqlite3

import pytest

from storageweb.db import available_migrations, connect, init_db, migrate, schema_version
from storageweb.db import connection


def test_fresh_database_gets_latest_version(tmp_path):
    db = str(tmp_path / "a.db")
    applied = init_db(db)
    latest = available_migrations()[-1][0]
    assert applied == list(range(1, latest + 1))
    conn = connect(db)
    assert schema_version(conn) == latest
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "audit_log", "settings", "uploads"} <= tables


def test_idempotent(tmp_path):
    db = str(tmp_path / "a.db")
    init_db(db)
    assert init_db(db) == []


def test_initial_schema_has_the_builtin_group_and_public_ids(tmp_path):
    """La 001 crea el grupo de serie «admins» con su identificador público, y el uid es obligatorio."""
    db = str(tmp_path / "a.db")
    init_db(db)
    conn = connect(db)
    row = conn.execute("SELECT name, builtin, uid FROM groups").fetchone()
    assert (row["name"], row["builtin"]) == ("admins", 1) and len(row["uid"]) == 36
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO users (username, source, created_at) VALUES ('ana', 'local', 'x')")


def test_migrations_are_consecutive():
    versions = [v for v, _ in available_migrations()]
    assert versions == list(range(1, len(versions) + 1))


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_ok.sql").write_text("CREATE TABLE a (x INTEGER);", encoding="utf-8")
    (mig_dir / "002_rota.sql").write_text("CREATE TABLE b (x INTEGER); SELECT * FROM no_existe;",
                                          encoding="utf-8")
    monkeypatch.setattr(connection, "MIGRATIONS_DIR", mig_dir)
    conn = connect(str(tmp_path / "x.db"))
    with pytest.raises(sqlite3.Error):
        migrate(conn)
    assert schema_version(conn) == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables and "b" not in tables


def test_non_consecutive_migrations_rejected(tmp_path, monkeypatch):
    (tmp_path / "001_a.sql").write_text("", encoding="utf-8")
    (tmp_path / "003_c.sql").write_text("", encoding="utf-8")
    monkeypatch.setattr(connection, "MIGRATIONS_DIR", tmp_path)
    with pytest.raises(RuntimeError):
        available_migrations()

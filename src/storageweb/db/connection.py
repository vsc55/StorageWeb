"""Conexión a SQLite y migraciones versionadas.

Las migraciones son ficheros ``migrations/NNN_descripcion.sql`` que se aplican en orden, cada una
en una transacción. La versión aplicada se guarda en ``PRAGMA user_version``.

Reglas para añadir una migración:
  * Nuevo fichero con el siguiente número (``002_...sql``); nunca modificar una ya publicada.
  * Debe ser SQL válido para SQLite y no incluir BEGIN/COMMIT (se añaden automáticamente).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def available_migrations() -> list[tuple[int, Path]]:
    found = []
    for path in MIGRATIONS_DIR.iterdir():
        match = _MIGRATION_RE.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    found.sort()
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"Migraciones no consecutivas en {MIGRATIONS_DIR}: {versions}")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Aplica las migraciones pendientes. Devuelve las versiones aplicadas."""
    applied = []
    current = schema_version(conn)
    for version, path in available_migrations():
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise
        applied.append(version)
    return applied


def init_db(db_path: str) -> list[int]:
    conn = connect(db_path)
    try:
        return migrate(conn)
    finally:
        conn.close()

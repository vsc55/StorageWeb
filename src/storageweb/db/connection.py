"""Conexión a SQLite y migraciones versionadas.

Las migraciones son ficheros ``migrations/NNN_descripcion.sql`` que se aplican en orden, cada una
en una transacción. La versión aplicada se guarda en ``PRAGMA user_version``.

Reglas para añadir una migración:
  * Nuevo fichero con el siguiente número (``002_...sql``); nunca modificar una ya publicada.
  * Debe ser SQL válido para SQLite y no incluir BEGIN/COMMIT (se añaden automáticamente).
  * Si reconstruye una tabla (crear la nueva, copiar, borrar la vieja y renombrar), empieza por la
    línea ``-- foreign_keys: off``: se desactivan las claves ajenas durante la migración (si no, borrar
    la tabla vieja borraría en cascada sus filas relacionadas) y se comprueban antes de confirmarla.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
FK_OFF_MARKER = "-- foreign_keys: off"


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
        rebuild = sql.lstrip().startswith(FK_OFF_MARKER)
        if rebuild:
            conn.execute("PRAGMA foreign_keys=OFF")  # no tiene efecto dentro de una transacción
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};")
            broken = conn.execute("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise sqlite3.IntegrityError(f"Migration {version:03d} breaks foreign keys: {len(broken)} rows")
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            if rebuild:
                conn.execute("PRAGMA foreign_keys=ON")
        applied.append(version)
    return applied


def init_db(db_path: str) -> list[int]:
    conn = connect(db_path)
    try:
        return migrate(conn)
    finally:
        conn.close()

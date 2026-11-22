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
from pathlib import Path
from .. import clock

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
FK_OFF_MARKER = "-- foreign_keys: off"


now_iso = clock.now_iso      # los repositorios lo importan de aquí


def db_size(path: str) -> int:
    """Lo que ocupa la base de datos en el disco, con su WAL (lo escrito y aún no pasado al fichero)."""
    return sum(p.stat().st_size for p in (Path(path), Path(f"{path}-wal")) if p.exists())


def subtree(column: str, rel: str) -> tuple[str, tuple]:
    """``(condición, argumentos)`` SQL de «``rel`` y lo que tiene dentro» en la columna ``column`` (rutas
    relativas: ``informes`` casa con ``informes`` e ``informes/2026/a.pdf``, no con ``informes-viejos``)."""
    like = rel.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    return f"({column} = ? OR {column} LIKE ? ESCAPE '\\')", (rel, like)


def owner_filter(user_id: int | None, column: str = "user_id") -> tuple[str, tuple]:
    """``(condición, argumentos)`` para quedarse con las filas de ``user_id`` (``None``: todas). En la carpeta
    personal cada uno tiene la suya: lo que se mueve o se borra allí solo toca las filas de quien lo hace."""
    return ("", ()) if user_id is None else (f" AND {column} = ?", (user_id,))


def update_row(conn: sqlite3.Connection, table: str, row_id: int, fields: dict, allowed: set[str]) -> None:
    """``UPDATE <table> SET … WHERE id = ?`` con ``fields`` (ya preparados por el repositorio). Las columnas salen de
    ``allowed`` (nunca de quien llama: ``ValueError`` si pide otra); ``table`` es siempre un literal del repositorio."""
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Campos no actualizables: {', '.join(sorted(unknown))}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)  # claves validadas contra ``allowed``
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*fields.values(), row_id))  # noqa: S608
    conn.commit()


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

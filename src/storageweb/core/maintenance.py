"""Mantenimiento: retención de la auditoría, compactación, copias automáticas y limpieza.

``run_due`` ejecuta lo que toque (como mucho una vez al día cada tarea, salvo las copias, que
siguen su intervalo) y apunta cuándo se hizo en el documento ``maintenance_state`` de la tabla
``settings``. La capa web la llama de vez en cuando en un hilo aparte.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlite3 import Connection

from ..db.repositories import audit, sessions
from ..db.repositories import settings as settings_repo
from . import backup, ipban

STATE_KEY = "maintenance_state"
_log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def backup_dir(cfg: dict) -> Path:
    """Carpeta de las copias (la misma que usa ``storageweb backup`` por defecto)."""
    return Path(cfg["data_dir"]) / "backups"


def state(conn: Connection) -> dict:
    return settings_repo.get(conn, STATE_KEY) or {}


def _mark(conn: Connection, task: str) -> None:
    current = state(conn)
    current[task] = _iso(_now())
    settings_repo.put(conn, STATE_KEY, current, "system")


def db_stats(conn: Connection, database: str) -> dict:
    size = sum(Path(database + suffix).stat().st_size for suffix in ("", "-wal") if Path(database + suffix).exists())
    tables = {}
    for table in ("users", "audit_log", "sessions", "api_tokens", "ip_rules", "groups"):
        tables[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 (nombres fijos)
    oldest = conn.execute("SELECT MIN(ts) FROM audit_log").fetchone()[0]
    return {"size": size, "tables": tables, "audit_oldest": oldest}


def purge_audit(conn: Connection, days: int) -> int:
    """Borra las entradas de auditoría de hace más de ``days`` días."""
    if days <= 0:
        return 0
    cur = conn.execute("DELETE FROM audit_log WHERE ts < ?", (_iso(_now() - timedelta(days=days)),))
    conn.commit()
    return cur.rowcount


def vacuum(conn: Connection, database: str) -> tuple[int, int]:
    """Compacta la base de datos. Devuelve (tamaño antes, tamaño después)."""
    before = db_stats(conn, database)["size"]
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return before, db_stats(conn, database)["size"]


def list_backups(cfg: dict) -> list[dict]:
    result = []
    for path in reversed(backup.list_backups(backup_dir(cfg))):
        stat = path.stat()
        result.append({"name": path.name, "size": stat.st_size,
                       "created": _iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc))})
    return result


def backup_path(cfg: dict, name: str) -> Path | None:
    """Ruta de una copia por su nombre (solo nombres de copias existentes: nada de rutas)."""
    if os.sep in name or "/" in name or name.startswith("."):
        return None
    path = backup_dir(cfg) / name
    return path if path in backup.list_backups(backup_dir(cfg)) else None


def create_backup(cfg: dict) -> Path:
    keep = cfg["maintenance"]["backup_keep"]
    return backup.create(cfg, backup_dir(cfg), keep=keep or None)


def run_due(conn: Connection, cfg: dict) -> list[str]:
    """Ejecuta las tareas pendientes. Devuelve las que se hicieron."""
    done = []
    current = state(conn)
    maint = cfg["maintenance"]

    def due(task: str, hours: float) -> bool:
        last = current.get(task)
        return not last or last < _iso(_now() - timedelta(hours=hours))

    if due("cleanup", 1):
        idle = _iso(_now() - timedelta(hours=cfg["session"]["lifetime_hours"]))
        sessions.delete_idle(conn, idle)
        ipban.prune(conn, cfg)
        _mark(conn, "cleanup")
        done.append("cleanup")
    if maint["audit_retention_days"] and due("audit_purge", 24):
        removed = purge_audit(conn, maint["audit_retention_days"])
        if removed:
            audit.log(conn, "audit_purged", None, username="system", detail=str(removed))
        _mark(conn, "audit_purge")
        done.append("audit_purge")
    if maint["backup_interval_hours"] and due("backup", maint["backup_interval_hours"]):
        try:
            path = create_backup(cfg)
        except Exception as exc:  # noqa: BLE001 (se registra y se reintenta en el siguiente intervalo)
            _log.exception("Automatic backup failed")
            audit.log(conn, "backup_failed", None, username="system", detail=str(exc)[:200])
        else:
            audit.log(conn, "backup_created", path.name, username="system", detail="auto")
        _mark(conn, "backup")
        done.append("backup")
    return done

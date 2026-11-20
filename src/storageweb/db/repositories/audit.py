"""Registro de auditoría. Cada evento lleva su nivel (``storageweb/audit_levels.py``)."""
from __future__ import annotations

import logging
import sqlite3
from sqlite3 import Connection

from ..connection import now_iso
from ... import audit_levels, metrics, siem

_log = logging.getLogger(__name__)


def log(conn: Connection, action: str, target: str | None = None, *, username: str | None = None,
        ip: str | None = None, detail: str | None = None, level: str | None = None) -> None:
    """Registra un evento. Nunca lanza excepciones: la auditoría no debe romper la operación. ``level``: el de la
    acción si no se da (``audit_levels.level_of``); por debajo de ``audit.min_level`` no se guarda. Cada evento
    suma también en la métrica ``storageweb_events_total`` (inicios de sesión, fallos, subidas, descargas…) y, si
    ``audit.*`` lo pide, se reenvía al SIEM (``storageweb/siem.py``, en segundo plano)."""
    metrics.inc("storageweb_events_total", action=action)
    level = level if level in audit_levels.RANK else audit_levels.level_of(action, detail)
    if not audit_levels.recorded(level):
        return
    ts = now_iso()
    siem.emit(siem.event_of(ts, username, action, target, ip, detail, level))   # a la cola del SIEM, si lo hay
    try:
        conn.execute(
            "INSERT INTO audit_log (ts, username, action, target, ip, detail, level) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, username, action, target, ip, detail, level),
        )
        conn.commit()
    except sqlite3.Error:
        _log.exception("No se pudo escribir en audit_log")


def for_user(conn: Connection, username: str, limit: int = 10) -> list:
    """Eventos hechos por el usuario o sobre él (``target`` o ``detail`` = su nombre)."""
    return conn.execute(
        "SELECT * FROM audit_log WHERE username = ? OR target = ? OR detail = ? ORDER BY id DESC LIMIT ?",
        (username, username, username, int(limit))).fetchall()


def _filters(username: str | None, action: str | None, min_level: str | None = None) -> tuple[str, list]:
    where, params = " WHERE 1=1", []
    if min_level and min_level != "debug":
        levels = audit_levels.levels_from(min_level)
        where += f" AND level IN ({', '.join('?' * len(levels))})"
        params.extend(levels)
    if username:
        where += " AND username = ?"
        params.append(username)
    if action:
        where += " AND action = ?"
        params.append(action)
    return where, params


def recent(conn: Connection, limit: int = 100, username: str | None = None,
           action: str | None = None, offset: int = 0, min_level: str | None = None) -> list:
    """Las más recientes primero; ``offset`` para paginar; ``min_level``: de ese nivel hacia arriba."""
    where, params = _filters(username, action, min_level)
    return conn.execute(f"SELECT * FROM audit_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                        [*params, int(limit), max(int(offset), 0)]).fetchall()


def count(conn: Connection, username: str | None = None, action: str | None = None,
          min_level: str | None = None) -> int:
    where, params = _filters(username, action, min_level)
    return conn.execute(f"SELECT COUNT(*) FROM audit_log{where}", params).fetchone()[0]


def count_since(conn: Connection, action: str, since_iso: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ? AND ts >= ?",
                        (action, since_iso)).fetchone()[0]

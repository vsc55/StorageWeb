"""Registro de auditoría."""
from __future__ import annotations

import logging
import sqlite3

from . import conn_or_default, now_iso

log_ = logging.getLogger(__name__)


def log(action: str, target: str | None = None, *, username: str | None = None,
        ip: str | None = None, detail: str | None = None, conn: sqlite3.Connection | None = None) -> None:
    try:
        conn = conn_or_default(conn)
        conn.execute(
            "INSERT INTO audit_log (ts, username, action, target, ip, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), username, action, target, ip, detail),
        )
        conn.commit()
    except sqlite3.Error:
        log_.exception("No se pudo escribir en audit_log")


def recent(limit: int = 100, username: str | None = None, action: str | None = None,
           conn: sqlite3.Connection | None = None) -> list:
    query, params = "SELECT * FROM audit_log WHERE 1=1", []
    if username:
        query += " AND username = ?"
        params.append(username)
    if action:
        query += " AND action = ?"
        params.append(action)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return conn_or_default(conn).execute(query, params).fetchall()

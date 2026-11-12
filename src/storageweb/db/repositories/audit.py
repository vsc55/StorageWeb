"""Registro de auditoría."""
from __future__ import annotations

import logging
import sqlite3
from sqlite3 import Connection

from ..connection import now_iso

_log = logging.getLogger(__name__)


def log(conn: Connection, action: str, target: str | None = None, *, username: str | None = None,
        ip: str | None = None, detail: str | None = None) -> None:
    """Registra un evento. Nunca lanza excepciones: la auditoría no debe romper la operación."""
    try:
        conn.execute(
            "INSERT INTO audit_log (ts, username, action, target, ip, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), username, action, target, ip, detail),
        )
        conn.commit()
    except sqlite3.Error:
        _log.exception("No se pudo escribir en audit_log")


def for_user(conn: Connection, username: str, limit: int = 10) -> list:
    """Eventos hechos por el usuario o sobre él (``target`` o ``detail`` = su nombre)."""
    return conn.execute(
        "SELECT * FROM audit_log WHERE username = ? OR target = ? OR detail = ? ORDER BY id DESC LIMIT ?",
        (username, username, username, int(limit))).fetchall()


def recent(conn: Connection, limit: int = 100, username: str | None = None,
           action: str | None = None) -> list:
    query, params = "SELECT * FROM audit_log WHERE 1=1", []
    if username:
        query += " AND username = ?"
        params.append(username)
    if action:
        query += " AND action = ?"
        params.append(action)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return conn.execute(query, params).fetchall()

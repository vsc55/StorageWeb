"""Repositorio de ajustes (documentos JSON con número de revisión)."""
from __future__ import annotations

import json
import sqlite3

from . import conn_or_default, now_iso


def get(key: str, conn: sqlite3.Connection | None = None) -> dict | None:
    row = conn_or_default(conn).execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def revision(key: str, conn: sqlite3.Connection | None = None) -> int:
    row = conn_or_default(conn).execute("SELECT revision FROM settings WHERE key = ?", (key,)).fetchone()
    return row["revision"] if row else 0


def info(key: str, conn: sqlite3.Connection | None = None):
    return conn_or_default(conn).execute(
        "SELECT revision, updated_at, updated_by FROM settings WHERE key = ?", (key,)).fetchone()


def put(key: str, value: dict, username: str | None = None,
        conn: sqlite3.Connection | None = None) -> int:
    conn = conn_or_default(conn)
    conn.execute(
        """INSERT INTO settings (key, value, revision, updated_at, updated_by) VALUES (?, ?, 1, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, revision = settings.revision + 1,
                                          updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
        (key, json.dumps(value, ensure_ascii=False), now_iso(), username),
    )
    conn.commit()
    return revision(key, conn)

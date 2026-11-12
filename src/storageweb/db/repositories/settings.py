"""Repositorio de ajustes (documentos JSON con número de revisión)."""
from __future__ import annotations

import json
from sqlite3 import Connection

from ..connection import now_iso


def get(conn: Connection, key: str) -> dict | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def revision(conn: Connection, key: str) -> int:
    row = conn.execute("SELECT revision FROM settings WHERE key = ?", (key,)).fetchone()
    return row["revision"] if row else 0


def info(conn: Connection, key: str):
    return conn.execute("SELECT revision, updated_at, updated_by FROM settings WHERE key = ?",
                        (key,)).fetchone()


def put(conn: Connection, key: str, value: dict, username: str | None = None) -> int:
    conn.execute(
        """INSERT INTO settings (key, value, revision, updated_at, updated_by) VALUES (?, ?, 1, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, revision = settings.revision + 1,
                                          updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
        (key, json.dumps(value, ensure_ascii=False), now_iso(), username),
    )
    conn.commit()
    return revision(conn, key)

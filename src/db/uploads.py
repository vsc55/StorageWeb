"""Repositorio de subidas por partes en curso."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import conn_or_default, now_iso


def create(*, upload_id: str, user_id: int, root: str, dir_rel: str, dir_path: str, filename: str,
           size: int, conn: sqlite3.Connection | None = None) -> None:
    conn = conn_or_default(conn)
    now = now_iso()
    conn.execute(
        """INSERT INTO uploads (id, user_id, root, dir_rel, dir_path, filename, size, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (upload_id, user_id, root, dir_rel, dir_path, filename, size, now, now),
    )
    conn.commit()


def get(upload_id: str, conn: sqlite3.Connection | None = None):
    return conn_or_default(conn).execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()


def touch(upload_id: str, conn: sqlite3.Connection | None = None) -> None:
    conn = conn_or_default(conn)
    conn.execute("UPDATE uploads SET updated_at = ? WHERE id = ?", (now_iso(), upload_id))
    conn.commit()


def delete(upload_id: str, conn: sqlite3.Connection | None = None) -> None:
    conn = conn_or_default(conn)
    conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    conn.commit()


def stale(max_age_hours: int, conn: sqlite3.Connection | None = None) -> list:
    limit = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
    return conn_or_default(conn).execute(
        "SELECT * FROM uploads WHERE updated_at < ?", (limit,)).fetchall()

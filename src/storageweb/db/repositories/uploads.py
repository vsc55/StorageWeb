"""Repositorio de subidas por partes en curso."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from ..connection import now_iso


def create(conn: Connection, *, upload_id: str, user_id: int, root: str, dir_rel: str,
           dir_path: str, filename: str, size: int) -> None:
    now = now_iso()
    conn.execute(
        """INSERT INTO uploads (id, user_id, root, dir_rel, dir_path, filename, size, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (upload_id, user_id, root, dir_rel, dir_path, filename, size, now, now),
    )
    conn.commit()


def get(conn: Connection, upload_id: str):
    return conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()


def touch(conn: Connection, upload_id: str) -> None:
    conn.execute("UPDATE uploads SET updated_at = ? WHERE id = ?", (now_iso(), upload_id))
    conn.commit()


def delete(conn: Connection, upload_id: str) -> None:
    conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    conn.commit()


def stale(conn: Connection, max_age_hours: int) -> list:
    limit = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
    return conn.execute("SELECT * FROM uploads WHERE updated_at < ?", (limit,)).fetchall()

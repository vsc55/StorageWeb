"""Repositorio de sesiones iniciadas (tabla ``sessions``)."""
from __future__ import annotations

from sqlite3 import Connection

from ..connection import now_iso


def create(conn: Connection, session_id: str, user_id: int, ip: str | None, user_agent: str | None) -> None:
    now = now_iso()
    conn.execute("INSERT INTO sessions (id, user_id, created_at, last_seen, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                 (session_id, user_id, now, now, ip, (user_agent or "")[:300]))
    conn.commit()


def get(conn: Connection, session_id: str):
    return conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def touch(conn: Connection, session_id: str, ip: str | None) -> None:
    conn.execute("UPDATE sessions SET last_seen = ?, ip = ? WHERE id = ?", (now_iso(), ip, session_id))
    conn.commit()


def delete(conn: Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def delete_for_user(conn: Connection, user_id: int, keep: str | None = None) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE user_id = ? AND id != ?", (user_id, keep or ""))
    conn.commit()
    return cur.rowcount


def delete_idle(conn: Connection, before_iso: str) -> int:
    cur = conn.execute("DELETE FROM sessions WHERE last_seen < ?", (before_iso,))
    conn.commit()
    return cur.rowcount


def list_all(conn: Connection, user_id: int | None = None) -> list:
    sql = """SELECT s.*, u.username, u.display_name, u.source, u.role FROM sessions s
             JOIN users u ON u.id = s.user_id"""
    params: tuple = ()
    if user_id is not None:
        sql += " WHERE s.user_id = ?"
        params = (user_id,)
    return conn.execute(sql + " ORDER BY s.last_seen DESC", params).fetchall()


def count_for_user(conn: Connection, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0]

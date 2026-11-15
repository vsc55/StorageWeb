"""Repositorio de tokens de API personales."""
from __future__ import annotations

from sqlite3 import Connection

from ..connection import now_iso


def create(conn: Connection, *, user_id: int, name: str, token_hash: str, prefix: str, scope: str,
           expires_at: str | None) -> int:
    cur = conn.execute(
        """INSERT INTO api_tokens (user_id, name, token_hash, prefix, scope, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""", (user_id, name, token_hash, prefix, scope, now_iso(), expires_at))
    conn.commit()
    return cur.lastrowid


def get_by_hash(conn: Connection, token_hash: str):
    return conn.execute("SELECT * FROM api_tokens WHERE token_hash = ?", (token_hash,)).fetchone()


def get(conn: Connection, token_id: int):
    return conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone()


def list_for_user(conn: Connection, user_id: int) -> list:
    return conn.execute("SELECT * FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()


def list_all(conn: Connection) -> list:
    return conn.execute("""SELECT t.*, u.username, u.display_name, u.uid AS user_uid FROM api_tokens t
                           JOIN users u ON u.id = t.user_id
                           ORDER BY t.created_at DESC""").fetchall()


def touch(conn: Connection, token_id: int, ip: str | None) -> None:
    conn.execute("UPDATE api_tokens SET last_used_at = ?, last_ip = ? WHERE id = ?", (now_iso(), ip, token_id))
    conn.commit()


def delete(conn: Connection, token_id: int) -> None:
    conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    conn.commit()


def delete_for_user(conn: Connection, user_id: int) -> int:
    cur = conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount

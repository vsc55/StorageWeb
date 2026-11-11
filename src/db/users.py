"""Repositorio de usuarios."""
from __future__ import annotations

import sqlite3
from typing import Iterable

from . import conn_or_default, now_iso

_UPDATABLE = {"display_name", "email", "groups", "home_path", "enabled", "role", "password_hash",
              "external_id", "last_login"}


def _join_groups(groups: Iterable[str] | None) -> str:
    return ",".join(sorted({g.strip().lower() for g in (groups or []) if g and g.strip()}))


def groups_of(user) -> set[str]:
    return {x for x in (user["groups"] or "").split(",") if x}


def get_by_id(user_id: int, conn: sqlite3.Connection | None = None):
    return conn_or_default(conn).execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_by_username(username: str, conn: sqlite3.Connection | None = None):
    return conn_or_default(conn).execute(
        "SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_by_external(source: str, external_id: str, conn: sqlite3.Connection | None = None):
    return conn_or_default(conn).execute(
        "SELECT * FROM users WHERE source = ? AND external_id = ?", (source, external_id)).fetchone()


def list_all(conn: sqlite3.Connection | None = None, search: str = "") -> list:
    conn = conn_or_default(conn)
    if search:
        like = f"%{search}%"
        return conn.execute(
            "SELECT * FROM users WHERE username LIKE ? OR display_name LIKE ? OR email LIKE ? "
            "ORDER BY username", (like, like, like)).fetchall()
    return conn.execute("SELECT * FROM users ORDER BY username").fetchall()


def create(*, username: str, source: str, role: str = "user", password_hash: str | None = None,
           display_name: str | None = None, email: str | None = None, external_id: str | None = None,
           groups: Iterable[str] | None = None, home_path: str | None = None, enabled: bool = True,
           conn: sqlite3.Connection | None = None) -> int:
    conn = conn_or_default(conn)
    cur = conn.execute(
        """INSERT INTO users (username, display_name, email, source, role, password_hash,
                              external_id, groups, home_path, enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (username, display_name, email, source, role, password_hash, external_id,
         _join_groups(groups), home_path or None, 1 if enabled else 0, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def update(user_id: int, conn: sqlite3.Connection | None = None, **fields) -> None:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"Campos no actualizables: {', '.join(sorted(unknown))}")
    if not fields:
        return
    if "groups" in fields and not isinstance(fields["groups"], str):
        fields["groups"] = _join_groups(fields["groups"])
    if "enabled" in fields:
        fields["enabled"] = 1 if fields["enabled"] else 0
    if "home_path" in fields:
        fields["home_path"] = fields["home_path"] or None
    conn = conn_or_default(conn)
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))  # noqa: S608
    conn.commit()


def touch_login(user_id: int, conn: sqlite3.Connection | None = None, **fields) -> None:
    update(user_id, conn, last_login=now_iso(), **fields)


def delete(user_id: int, conn: sqlite3.Connection | None = None) -> None:
    conn = conn_or_default(conn)
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def count_admins(conn: sqlite3.Connection | None = None, exclude_id: int | None = None) -> int:
    row = conn_or_default(conn).execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND enabled = 1 AND id != ?",
        (exclude_id if exclude_id is not None else -1,)).fetchone()
    return row[0]

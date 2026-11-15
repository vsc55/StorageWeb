"""Repositorio de usuarios."""
from __future__ import annotations

import uuid
from sqlite3 import Connection
from typing import Iterable

from ..connection import now_iso

_UPDATABLE = {"display_name", "email", "groups", "home_path", "enabled", "role", "password_hash",
              "external_id", "last_login", "locale", "theme", "external_groups", "quota_mb", "disabled_reason"}
DIRECTORY = "directory"  # disabled_reason: lo desactivó el proveedor (se reactiva solo)


def _join_groups(groups: Iterable[str] | None) -> str:
    return ",".join(sorted({g.strip().lower() for g in (groups or []) if g and g.strip()}))


def groups_of(user) -> set[str]:
    return {x for x in (user["groups"] or "").split(",") if x}


def get_by_id(conn: Connection, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_by_uid(conn: Connection, uid: str):
    """Por el identificador público (el de las direcciones de la administración)."""
    return conn.execute("SELECT * FROM users WHERE uid = ?", (uid,)).fetchone()


def get_by_username(conn: Connection, username: str):
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_by_external(conn: Connection, source: str, external_id: str):
    return conn.execute("SELECT * FROM users WHERE source = ? AND external_id = ?",
                        (source, external_id)).fetchone()


def rename(conn: Connection, user_id: int, username: str) -> None:
    conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
    conn.commit()


def directory_candidates(conn: Connection, source: str) -> list:
    """Cuentas de un origen que hay que revisar contra su directorio: las que pueden entrar ahora mismo sin pasar
    por el proveedor (sesión abierta o token de API vigente) y las que desactivó el propio directorio."""
    return conn.execute(
        """SELECT * FROM users u WHERE u.source = ? AND u.external_id IS NOT NULL AND (
               u.disabled_reason = ? OR (u.enabled = 1 AND (
                   EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = u.id) OR
                   EXISTS (SELECT 1 FROM api_tokens t WHERE t.user_id = u.id AND
                           (t.expires_at IS NULL OR t.expires_at > ?)))))
           ORDER BY u.username""", (source, DIRECTORY, now_iso())).fetchall()


def list_all(conn: Connection, search: str = "", *, status: str | None = None, source: str | None = None,
             role: str | None = None, group_id: int | None = None) -> list:
    """Usuarios filtrados. ``status`` = active | disabled; ``group_id`` = miembros de ese grupo."""
    where, params = [], []
    if search:
        like = f"%{search}%"
        where.append("(username LIKE ? OR display_name LIKE ? OR email LIKE ?)")
        params += [like, like, like]
    if status in ("active", "disabled"):
        where.append("enabled = ?")
        params.append(1 if status == "active" else 0)
    if source:
        where.append("source = ?")
        params.append(source)
    if role:
        where.append("role = ?")
        params.append(role)
    if group_id is not None:
        builtin = conn.execute("SELECT builtin FROM groups WHERE id = ?", (group_id,)).fetchone()
        if builtin is not None and builtin[0]:
            where.append("role = 'admin'")  # el grupo de serie «admins» lo da el rol
        else:
            where.append("id IN (SELECT user_id FROM user_groups WHERE group_id = ?)")
            params.append(group_id)
    sql = "SELECT * FROM users" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY username"
    return conn.execute(sql, params).fetchall()  # noqa: S608 (condiciones fijas, valores parametrizados)


def count_by_source(conn: Connection) -> dict:
    return {r[0]: r[1] for r in conn.execute("SELECT source, COUNT(*) FROM users GROUP BY source")}


def counts(conn: Connection) -> dict:
    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(enabled), 0) FROM users").fetchone()
    return {"all": row[0], "active": row[1], "disabled": row[0] - row[1]}


def create(conn: Connection, *, username: str, source: str, role: str = "user",
           password_hash: str | None = None, display_name: str | None = None,
           email: str | None = None, external_id: str | None = None,
           groups: Iterable[str] | None = None, home_path: str | None = None,
           enabled: bool = True) -> int:
    cur = conn.execute(
        """INSERT INTO users (username, display_name, email, source, role, password_hash,
                              external_id, groups, home_path, enabled, created_at, uid)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (username, display_name, email, source, role, password_hash, external_id,
         _join_groups(groups), home_path or None, 1 if enabled else 0, now_iso(), str(uuid.uuid4())),
    )
    conn.commit()
    return cur.lastrowid


def update(conn: Connection, user_id: int, **fields) -> None:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"Campos no actualizables: {', '.join(sorted(unknown))}")
    if not fields:
        return
    for key in ("groups", "external_groups"):
        if key in fields and not isinstance(fields[key], str):
            fields[key] = _join_groups(fields[key])
    if "enabled" in fields:
        fields["enabled"] = 1 if fields["enabled"] else 0
    if "home_path" in fields:
        fields["home_path"] = fields["home_path"] or None
    sets = ", ".join(f"{k} = ?" for k in fields)  # claves validadas contra _UPDATABLE
    conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))  # noqa: S608
    conn.commit()


def touch_login(conn: Connection, user_id: int, **fields) -> None:
    update(conn, user_id, last_login=now_iso(), **fields)


def delete(conn: Connection, user_id: int) -> None:
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()


def count_admins(conn: Connection, exclude_id: int | None = None) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND enabled = 1 AND id != ?",
        (exclude_id if exclude_id is not None else -1,)).fetchone()[0]

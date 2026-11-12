"""Repositorio de grupos y pertenencias (tablas ``groups`` y ``user_groups``)."""
from __future__ import annotations

from sqlite3 import Connection
from typing import Iterable

from ..connection import now_iso

_UPDATABLE = {"label", "description", "source", "external_id"}

_WITH_COUNTS = """
    SELECT g.*,
           CASE WHEN g.builtin THEN (SELECT COUNT(*) FROM users WHERE role = 'admin')
                ELSE (SELECT COUNT(*) FROM user_groups ug WHERE ug.group_id = g.id) END AS members,
           (SELECT COUNT(*) FROM user_groups ug WHERE ug.group_id = g.id AND ug.origin = 'manual') AS manual_members
    FROM groups g
"""


def get_by_id(conn: Connection, group_id: int):
    return conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()


def get_by_name(conn: Connection, name: str):
    return conn.execute("SELECT * FROM groups WHERE name = ?", (name,)).fetchone()


def get_builtin(conn: Connection, name: str):
    return conn.execute("SELECT * FROM groups WHERE builtin = 1 AND name = ?", (name,)).fetchone()


def get_by_external(conn: Connection, source: str, external_id: str):
    return conn.execute("SELECT * FROM groups WHERE source = ? AND external_id = ?",
                        (source, external_id)).fetchone()


def list_all(conn: Connection, search: str = "", source: str | None = None) -> list:
    where, params = [], []
    if search:
        like = f"%{search}%"
        where.append("(g.name LIKE ? OR g.label LIKE ? OR g.description LIKE ?)")
        params += [like, like, like]
    if source:
        where.append("g.source = ?")
        params.append(source)
    sql = _WITH_COUNTS + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY g.builtin DESC, g.label COLLATE NOCASE"  # el grupo de serie, primero
    return conn.execute(sql, params).fetchall()


def create(conn: Connection, *, name: str, label: str, description: str = "", source: str = "local",
           external_id: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO groups (name, label, description, source, external_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name, label, description or "", source, external_id or None, now_iso()))
    conn.commit()
    return cur.lastrowid


def update(conn: Connection, group_id: int, **fields) -> None:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"Campos no actualizables: {', '.join(sorted(unknown))}")
    if not fields:
        return
    if "external_id" in fields:
        fields["external_id"] = fields["external_id"] or None
    sets = ", ".join(f"{k} = ?" for k in fields)  # claves validadas contra _UPDATABLE
    conn.execute(f"UPDATE groups SET {sets} WHERE id = ?", (*fields.values(), group_id))  # noqa: S608
    conn.commit()


def delete(conn: Connection, group_id: int) -> None:
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()


# --------------------------------------------------------------------------- pertenencias

def admins(conn: Connection) -> list:
    """Miembros del grupo de serie «admins»: los usuarios con rol admin."""
    return conn.execute("SELECT u.*, 'role' AS origin, NULL AS added_at FROM users u WHERE u.role = 'admin' "
                        "ORDER BY u.username").fetchall()


def members(conn: Connection, group_id: int) -> list:
    return conn.execute(
        """SELECT u.*, ug.origin, ug.added_at FROM user_groups ug JOIN users u ON u.id = ug.user_id
           WHERE ug.group_id = ? ORDER BY ug.origin, u.username""", (group_id,)).fetchall()


def member_ids(conn: Connection, group_id: int) -> list[int]:
    return [r[0] for r in conn.execute("SELECT user_id FROM user_groups WHERE group_id = ?", (group_id,))]


def memberships(conn: Connection, user_id: int) -> list:
    """Grupos de un usuario con el origen de cada pertenencia."""
    return conn.execute(
        """SELECT g.*, ug.origin FROM user_groups ug JOIN groups g ON g.id = ug.group_id
           WHERE ug.user_id = ? ORDER BY g.builtin DESC, g.label COLLATE NOCASE""", (user_id,)).fetchall()


def get_membership(conn: Connection, user_id: int, group_id: int):
    return conn.execute("SELECT * FROM user_groups WHERE user_id = ? AND group_id = ?",
                        (user_id, group_id)).fetchone()


def add_member(conn: Connection, user_id: int, group_id: int, origin: str) -> None:
    """Añade la pertenencia. Una manual nunca se degrada a 'sync'."""
    if origin == "manual":
        conn.execute(
            """INSERT INTO user_groups (user_id, group_id, origin, added_at) VALUES (?, ?, 'manual', ?)
               ON CONFLICT(user_id, group_id) DO UPDATE SET origin = 'manual'""", (user_id, group_id, now_iso()))
    else:
        conn.execute("INSERT OR IGNORE INTO user_groups (user_id, group_id, origin, added_at) VALUES (?, ?, ?, ?)",
                     (user_id, group_id, origin, now_iso()))
    conn.commit()


def remove_member(conn: Connection, user_id: int, group_id: int) -> None:
    conn.execute("DELETE FROM user_groups WHERE user_id = ? AND group_id = ?", (user_id, group_id))
    conn.commit()


def replace_sync(conn: Connection, user_id: int, source: str, group_ids: Iterable[int]) -> None:
    """Deja como pertenencias 'sync' de ``source`` exactamente ``group_ids`` (las manuales no se tocan)."""
    ids = set(group_ids)
    conn.execute(
        """DELETE FROM user_groups WHERE user_id = ? AND origin = 'sync'
           AND group_id IN (SELECT id FROM groups WHERE source = ?)""", (user_id, source))
    now = now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO user_groups (user_id, group_id, origin, added_at) VALUES (?, ?, 'sync', ?)",
        [(user_id, gid, now) for gid in sorted(ids)])
    conn.commit()


def member_names(conn: Connection, user_id: int) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT g.name FROM user_groups ug JOIN groups g ON g.id = ug.group_id WHERE ug.user_id = ?", (user_id,))}

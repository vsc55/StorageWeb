"""Repositorio de los roles propios (tabla ``roles``, migración 007). Las reglas, en ``core/roles.py``."""
from __future__ import annotations

from sqlite3 import Connection

from ..connection import now_iso


def _perms(text: str) -> list[str]:
    return [p for p in (text or "").split(",") if p]


def as_dict(row) -> dict:
    return {"key": row["key"], "label": row["label"], "description": row["description"],
            "permissions": _perms(row["permissions"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_all(conn: Connection) -> list[dict]:
    return [as_dict(r) for r in conn.execute("SELECT * FROM roles ORDER BY label COLLATE NOCASE")]


def get(conn: Connection, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM roles WHERE key = ?", (key,)).fetchone()
    return as_dict(row) if row else None


def create(conn: Connection, key: str, label: str, description: str, permissions: list[str]) -> None:
    now = now_iso()
    conn.execute("INSERT INTO roles (key, label, description, permissions, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (key, label, description, ",".join(permissions), now, now))
    conn.commit()


def update(conn: Connection, key: str, label: str, description: str, permissions: list[str]) -> None:
    conn.execute("UPDATE roles SET label = ?, description = ?, permissions = ?, updated_at = ? WHERE key = ?",
                 (label, description, ",".join(permissions), now_iso(), key))
    conn.commit()


def delete(conn: Connection, key: str) -> None:
    conn.execute("DELETE FROM roles WHERE key = ?", (key,))
    conn.commit()


def usage(conn: Connection, key: str) -> dict:
    """Quién lo tiene: ``{"users": [usernames], "groups": [nombres]}``."""
    return {"users": [r[0] for r in conn.execute("SELECT username FROM users WHERE role = ? ORDER BY username", (key,))],
            "groups": [r[0] for r in conn.execute("SELECT label FROM groups WHERE role = ? ORDER BY label", (key,))]}


def counts(conn: Connection) -> dict[str, dict]:
    """``{clave: {"users": n, "groups": n}}`` de todos los roles (también admin y user)."""
    out: dict[str, dict] = {}
    for role, n in conn.execute("SELECT role, COUNT(*) FROM users GROUP BY role"):
        out.setdefault(role, {"users": 0, "groups": 0})["users"] = n
    for role, n in conn.execute("SELECT role, COUNT(*) FROM groups WHERE role IS NOT NULL GROUP BY role"):
        out.setdefault(role, {"users": 0, "groups": 0})["groups"] = n
    return out


def move_users(conn: Connection, key: str, to: str) -> int:
    cur = conn.execute("UPDATE users SET role = ? WHERE role = ?", (to, key))
    conn.commit()
    return cur.rowcount


def clear_groups(conn: Connection, key: str) -> int:
    cur = conn.execute("UPDATE groups SET role = NULL WHERE role = ?", (key,))
    conn.commit()
    return cur.rowcount


def group_roles(conn: Connection) -> dict[str, str]:
    """``{nombre del grupo en minúsculas: rol}`` de los grupos que dan un rol a sus miembros."""
    return {str(name).lower(): role for name, role in conn.execute("SELECT name, role FROM groups WHERE role IS NOT NULL")}

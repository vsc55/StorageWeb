"""Repositorio de las carpetas compartidas, las ubicaciones y las cuotas de grupo guardadas desde la web.

Trabaja con los mismos diccionarios que la configuración (``storage.shares[]``, ``storage.locations[]``,
``storage.group_quotas``): la conversión a filas está aquí. Las escrituras no hacen ``commit``: las agrupa
quien llama en una transacción (``settings.runtime``).
"""
from __future__ import annotations

import json
from sqlite3 import Connection

from ..connection import now_iso

SHARE_COLUMNS = ("label", "location", "path", "read_only", "quota_mb")
LOCATION_COLUMNS = ("name", "label", "type")


# --------------------------------------------------------------------------- carpetas compartidas

def _access_rows(share: dict) -> list[tuple[str, str, str]]:
    """Las cuatro listas de la configuración → filas (kind, ref, level)."""
    ro_users = set(share.get("read_only_users") or [])
    ro_groups = set(share.get("read_only_groups") or [])
    rows = []
    users = share["users"] if "users" in share else ["*"]  # como en config.json: sin «users», todos
    for ref in users or []:
        kind = "all" if ref == "*" else "user"
        rows.append((kind, ref, "read" if ref in ro_users else "write"))
    for ref in share.get("groups") or []:
        rows.append(("group", ref, "read" if ref in ro_groups else "write"))
    return rows


def list_shares(conn: Connection, profile: str) -> list[dict]:
    shares = []
    for row in conn.execute("SELECT * FROM shares WHERE profile = ? ORDER BY position, name", (profile,)):
        share = {"name": row["name"], "label": row["label"], "location": row["location"], "path": row["path"],
                 "read_only": bool(row["read_only"]), "quota_mb": row["quota_mb"],
                 "users": [], "read_only_users": [], "groups": [], "read_only_groups": []}
        for acc in conn.execute("SELECT kind, ref, level FROM share_access WHERE profile = ? AND share = ? "
                                "ORDER BY kind = 'all' DESC, kind, ref", (profile, row["name"])):
            users, read_only = ("groups", "read_only_groups") if acc["kind"] == "group" else ("users", "read_only_users")
            share[users].append(acc["ref"])
            if acc["level"] == "read":
                share[read_only].append(acc["ref"])
        shares.append(share)
    return shares


def save_share(conn: Connection, profile: str, share: dict, position: int, username: str | None,
               original: str | None = None) -> None:
    """Crea o sustituye una carpeta (``original``: su nombre anterior, si se renombra) con sus accesos."""
    old = original or share["name"]
    exists = conn.execute("SELECT 1 FROM shares WHERE profile = ? AND name = ?", (profile, old)).fetchone()
    # Los mismos valores por defecto que en config.json (el nombre como etiqueta, sin cuota…)
    values = (str(share.get("label") or share["name"]), share.get("location") or "", str(share.get("path") or ""),
              int(bool(share.get("read_only"))), int(share.get("quota_mb") or 0), position, now_iso(), username)
    if exists:
        conn.execute("UPDATE shares SET name = ?, label = ?, location = ?, path = ?, read_only = ?, quota_mb = ?, "
                     "position = ?, updated_at = ?, updated_by = ? WHERE profile = ? AND name = ?",
                     (share["name"], *values, profile, old))  # el acceso sigue al nombre (ON UPDATE CASCADE)
    else:
        conn.execute("INSERT INTO shares (name, label, location, path, read_only, quota_mb, position, updated_at, "
                     "updated_by, profile) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (share["name"], *values, profile))
    conn.execute("DELETE FROM share_access WHERE profile = ? AND share = ?", (profile, share["name"]))
    conn.executemany("INSERT OR IGNORE INTO share_access (profile, share, kind, ref, level) VALUES (?, ?, ?, ?, ?)",
                     [(profile, share["name"], *row) for row in _access_rows(share)])


def move_share(conn: Connection, profile: str, name: str, position: int) -> None:
    conn.execute("UPDATE shares SET position = ? WHERE profile = ? AND name = ?", (position, profile, name))


def delete_share(conn: Connection, profile: str, name: str) -> None:
    conn.execute("DELETE FROM shares WHERE profile = ? AND name = ?", (profile, name))


# --------------------------------------------------------------------------- ubicaciones

def list_locations(conn: Connection, profile: str) -> list[dict]:
    """Las ubicaciones con sus opciones (los secretos, tal cual: cifrados)."""
    result = []
    for row in conn.execute("SELECT * FROM locations WHERE profile = ? ORDER BY position, name", (profile,)):
        loc = {"name": row["name"], "label": row["label"], "type": row["type"]}
        for opt in conn.execute("SELECT name, value FROM location_options WHERE profile = ? AND location = ? "
                                "ORDER BY name", (profile, row["name"])):
            loc[opt["name"]] = json.loads(opt["value"])
        result.append(loc)
    return result


def save_location(conn: Connection, profile: str, loc: dict, position: int, username: str | None,
                  original: str | None = None) -> None:
    old = original or loc["name"]
    exists = conn.execute("SELECT 1 FROM locations WHERE profile = ? AND name = ?", (profile, old)).fetchone()
    if exists:
        conn.execute("UPDATE locations SET name = ?, label = ?, type = ?, position = ?, updated_at = ?, updated_by = ? "
                     "WHERE profile = ? AND name = ?",
                     (loc["name"], loc.get("label") or loc["name"], loc["type"], position, now_iso(), username,
                      profile, old))
    else:
        conn.execute("INSERT INTO locations (profile, name, label, type, position, updated_at, updated_by) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (profile, loc["name"], loc.get("label") or loc["name"], loc["type"], position, now_iso(), username))
    conn.execute("DELETE FROM location_options WHERE profile = ? AND location = ?", (profile, loc["name"]))
    conn.executemany("INSERT INTO location_options (profile, location, name, value, secret) VALUES (?, ?, ?, ?, ?)",
                     [(profile, loc["name"], key, json.dumps(value, ensure_ascii=False),
                       int(isinstance(value, str) and value.startswith("enc:v1:")))
                      for key, value in loc.items() if key not in LOCATION_COLUMNS and key != "origin"])


def move_location(conn: Connection, profile: str, name: str, position: int) -> None:
    conn.execute("UPDATE locations SET position = ? WHERE profile = ? AND name = ?", (position, profile, name))


def delete_location(conn: Connection, profile: str, name: str) -> None:
    conn.execute("DELETE FROM locations WHERE profile = ? AND name = ?", (profile, name))


# --------------------------------------------------------------------------- cuotas de grupo

def group_quotas(conn: Connection) -> dict[str, int]:
    return {row["name"]: row["home_quota_mb"] for row in
            conn.execute("SELECT name, home_quota_mb FROM groups WHERE home_quota_mb IS NOT NULL ORDER BY name")}


def set_group_quota(conn: Connection, name: str, quota_mb: int | None) -> bool:
    """``False`` si el grupo no existe."""
    cur = conn.execute("UPDATE groups SET home_quota_mb = ? WHERE name = ?", (quota_mb, name))
    return cur.rowcount > 0


def bump_all(conn: Connection, username: str | None) -> None:
    """Las cuotas de grupo son de todos los perfiles: todos tienen que recalcular sus ajustes."""
    conn.execute("UPDATE settings_profiles SET revision = revision + 1, updated_at = ?, updated_by = ?",
                 (now_iso(), username))

"""Repositorio de los ajustes web por campo (tablas ``settings_values`` y ``settings_profiles``).

Solo lee y escribe filas; qué es un campo, la validación y el cifrado son de ``settings.store`` y
``settings.runtime``. Las escrituras no hacen ``commit``: las agrupa quien llama en una transacción.
"""
from __future__ import annotations

import json
from sqlite3 import Connection

from ..connection import now_iso


def rows(conn: Connection, profile: str) -> list:
    return conn.execute("SELECT path, value, secret, updated_at, updated_by FROM settings_values "
                        "WHERE profile = ? ORDER BY path", (profile,)).fetchall()


def values(conn: Connection, profile: str) -> dict:
    """``{ruta: valor}`` (JSON ya leído; los secretos, tal cual: cifrados)."""
    return {row["path"]: json.loads(row["value"]) for row in rows(conn, profile)}


def upsert(conn: Connection, profile: str, path: str, value, *, secret: bool, username: str | None) -> None:
    conn.execute("""INSERT INTO settings_values (profile, path, value, secret, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile, path) DO UPDATE SET value = excluded.value, secret = excluded.secret,
                        updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                 (profile, path, json.dumps(value, ensure_ascii=False), int(secret), now_iso(), username))


def delete(conn: Connection, profile: str, path: str) -> None:
    conn.execute("DELETE FROM settings_values WHERE profile = ? AND path = ?", (profile, path))


def bump(conn: Connection, profile: str, username: str | None) -> None:
    conn.execute("""INSERT INTO settings_profiles (name, revision, updated_at, updated_by) VALUES (?, 1, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET revision = settings_profiles.revision + 1,
                        updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                 (profile, now_iso(), username))


def revision(conn: Connection, profile: str) -> int:
    row = conn.execute("SELECT revision FROM settings_profiles WHERE name = ?", (profile,)).fetchone()
    return row["revision"] if row else 0


def info(conn: Connection, profile: str):
    """Último cambio del perfil: ``revision``, ``updated_at``, ``updated_by`` (o ``None``)."""
    return conn.execute("SELECT revision, updated_at, updated_by FROM settings_profiles WHERE name = ?",
                        (profile,)).fetchone()


def profiles(conn: Connection) -> list:
    """Perfiles con ajustes guardados: nombre, número de campos y último cambio."""
    return conn.execute("""SELECT p.name, p.updated_at, p.updated_by,
                                  (SELECT COUNT(*) FROM settings_values v WHERE v.profile = p.name) AS fields
                           FROM settings_profiles p ORDER BY p.name""").fetchall()

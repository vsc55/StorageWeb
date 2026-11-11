"""Acceso a SQLite: usuarios y registro de auditoría."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT,
    email         TEXT,
    source        TEXT NOT NULL CHECK (source IN ('local', 'pam', 'entra')),
    password_hash TEXT,
    external_id   TEXT,
    groups        TEXT NOT NULL DEFAULT '',
    home_path     TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_external
    ON users(source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    username TEXT,
    action   TEXT NOT NULL,
    target   TEXT,
    ip       TEXT,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["SW"]["database"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --------------------------------------------------------------------------- users

def get_user_by_id(user_id: int):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_username(username: str, conn: sqlite3.Connection | None = None):
    conn = conn or get_db()
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user_by_external(source: str, external_id: str):
    return get_db().execute(
        "SELECT * FROM users WHERE source = ? AND external_id = ?", (source, external_id)
    ).fetchone()


def create_user(conn: sqlite3.Connection, *, username: str, source: str, password_hash=None,
                display_name=None, email=None, external_id=None, groups: list[str] | None = None,
                home_path=None) -> int:
    cur = conn.execute(
        """INSERT INTO users (username, display_name, email, source, password_hash,
                              external_id, groups, home_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (username, display_name, email, source, password_hash, external_id,
         ",".join(groups or []), home_path, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def touch_login(user_id: int, *, display_name=None, email=None, groups: list[str] | None = None) -> None:
    db = get_db()
    fields, values = ["last_login = ?"], [now_iso()]
    if display_name is not None:
        fields.append("display_name = ?"); values.append(display_name)
    if email is not None:
        fields.append("email = ?"); values.append(email)
    if groups is not None:
        fields.append("groups = ?"); values.append(",".join(groups))
    values.append(user_id)
    db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()


def user_groups(user) -> set[str]:
    return {x.strip().lower() for x in (user["groups"] or "").split(",") if x.strip()}


# --------------------------------------------------------------------------- audit

def audit(action: str, target: str | None = None, *, username: str | None = None,
          ip: str | None = None, detail: str | None = None) -> None:
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_log (ts, username, action, target, ip, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), username, action, target, ip, detail),
        )
        db.commit()
    except sqlite3.Error:
        current_app.logger.exception("No se pudo escribir en audit_log")

"""Repositorio de reglas de IP (bloqueadas y permitidas) e infracciones recientes."""
from __future__ import annotations

from sqlite3 import Connection

from ..connection import now_iso


def list_rules(conn: Connection, kind: str | None = None) -> list:
    if kind:
        return conn.execute("SELECT * FROM ip_rules WHERE kind = ? ORDER BY created_at DESC", (kind,)).fetchall()
    return conn.execute("SELECT * FROM ip_rules ORDER BY created_at DESC").fetchall()


def get(conn: Connection, rule_id: int):
    return conn.execute("SELECT * FROM ip_rules WHERE id = ?", (rule_id,)).fetchone()


def add(conn: Connection, kind: str, network: str, *, reason: str = "", automatic: bool = False,
        created_by: str | None = None, expires_at: str | None = None) -> int:
    """Crea la regla o, si ya existe, la renueva (motivo y caducidad)."""
    cur = conn.execute(
        """INSERT INTO ip_rules (kind, network, reason, automatic, created_at, created_by, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(kind, network) DO UPDATE SET reason = excluded.reason, automatic = excluded.automatic,
               created_at = excluded.created_at, created_by = excluded.created_by, expires_at = excluded.expires_at""",
        (kind, network, reason, 1 if automatic else 0, now_iso(), created_by, expires_at))
    conn.commit()
    return cur.lastrowid


def delete(conn: Connection, rule_id: int) -> None:
    conn.execute("DELETE FROM ip_rules WHERE id = ?", (rule_id,))
    conn.commit()


def delete_network(conn: Connection, kind: str, network: str) -> int:
    cur = conn.execute("DELETE FROM ip_rules WHERE kind = ? AND network = ?", (kind, network))
    conn.commit()
    return cur.rowcount


def delete_all(conn: Connection, kind: str) -> int:
    cur = conn.execute("DELETE FROM ip_rules WHERE kind = ?", (kind,))
    conn.commit()
    return cur.rowcount


def delete_expired(conn: Connection) -> int:
    cur = conn.execute("DELETE FROM ip_rules WHERE expires_at IS NOT NULL AND expires_at < ?", (now_iso(),))
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- infracciones

def add_offense(conn: Connection, ip: str, kind: str) -> None:
    conn.execute("INSERT INTO ip_offenses (ip, ts, kind) VALUES (?, ?, ?)", (ip, now_iso(), kind))
    conn.commit()


def count_offenses(conn: Connection, ip: str, since_iso: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM ip_offenses WHERE ip = ? AND ts >= ?", (ip, since_iso)).fetchone()[0]


def clear_offenses(conn: Connection, ip: str | None = None, before_iso: str | None = None) -> None:
    if ip is not None:
        conn.execute("DELETE FROM ip_offenses WHERE ip = ?", (ip,))
    elif before_iso is not None:
        conn.execute("DELETE FROM ip_offenses WHERE ts < ?", (before_iso,))
    conn.commit()

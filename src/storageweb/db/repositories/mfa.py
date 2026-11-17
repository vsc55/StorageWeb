"""Repositorio de la verificación en dos pasos (tablas ``mfa_factors`` y ``mfa_recovery``).

Solo filas: la semilla llega y sale **cifrada** (la cifra y descifra :mod:`storageweb.core.mfa`), y de los códigos de
recuperación solo se guarda el hash. Las dos operaciones que deciden si un código vale son atómicas en el propio SQL
(``note_step`` y ``consume_recovery``): de dos peticiones a la vez con el mismo código, solo una cambia la fila.
"""
from __future__ import annotations

from sqlite3 import Connection

from ..connection import now_iso


def factor(conn: Connection, user_id: int):
    return conn.execute("SELECT * FROM mfa_factors WHERE user_id = ?", (user_id,)).fetchone()


def begin(conn: Connection, user_id: int, sealed_secret: str) -> None:
    """Empieza (o vuelve a empezar) un alta: una semilla nueva, sin confirmar. Sustituye cualquier factor anterior y
    sus códigos (empezar un alta con uno activo solo pasa al forzarla, y entonces ya no vale)."""
    now = now_iso()
    conn.execute("DELETE FROM mfa_recovery WHERE user_id = ?", (user_id,))
    conn.execute("INSERT OR REPLACE INTO mfa_factors (user_id, method, secret, confirmed, last_step, created_at, "
                 "updated_at) VALUES (?, 'totp', ?, 0, -1, ?, ?)", (user_id, sealed_secret, now, now))
    conn.commit()


def confirm(conn: Connection, user_id: int, step: int) -> bool:
    """Activa un alta comprobada; ``step`` (el del código que la comprobó) ya queda gastado."""
    cur = conn.execute("UPDATE mfa_factors SET confirmed = 1, last_step = ?, updated_at = ? "
                       "WHERE user_id = ? AND confirmed = 0", (step, now_iso(), user_id))
    conn.commit()
    return cur.rowcount == 1


def note_step(conn: Connection, user_id: int, step: int) -> bool:
    """Gasta el paso ``step``. Solo cambia la fila si su último paso es ANTERIOR: de dos peticiones con el mismo código
    que leyeron el factor a la vez, solo una gana (la otra no cambia nada y no es un sí)."""
    cur = conn.execute("UPDATE mfa_factors SET last_step = ?, updated_at = ? "
                       "WHERE user_id = ? AND confirmed = 1 AND last_step < ?", (step, now_iso(), user_id, step))
    conn.commit()
    return cur.rowcount == 1


def delete(conn: Connection, user_id: int) -> bool:
    """Quita el factor y sus códigos. Devuelve si había factor."""
    cur = conn.execute("DELETE FROM mfa_factors WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM mfa_recovery WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def set_recovery(conn: Connection, user_id: int, code_hashes: list[str]) -> None:
    """Sustituye entero el juego de códigos (nunca se añaden: regenerar es lo que se hace si se filtró la lista)."""
    conn.execute("DELETE FROM mfa_recovery WHERE user_id = ?", (user_id,))
    conn.executemany("INSERT INTO mfa_recovery (user_id, code_hash) VALUES (?, ?)", [(user_id, h) for h in code_hashes])
    conn.commit()


def recovery_unused(conn: Connection, user_id: int) -> list:
    return conn.execute("SELECT id, code_hash FROM mfa_recovery WHERE user_id = ? AND used_at IS NULL",
                        (user_id,)).fetchall()


def recovery_left(conn: Connection, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM mfa_recovery WHERE user_id = ? AND used_at IS NULL",
                        (user_id,)).fetchone()[0]


def consume_recovery(conn: Connection, code_id: int) -> bool:
    """Gasta un código. Solo cambia una fila que seguía sin usar: dos peticiones con el mismo código, un solo sí."""
    cur = conn.execute("UPDATE mfa_recovery SET used_at = ? WHERE id = ? AND used_at IS NULL", (now_iso(), code_id))
    conn.commit()
    return cur.rowcount == 1


def enrolled_ids(conn: Connection) -> set[int]:
    """Los ids de las cuentas con un factor activo (una consulta para toda una lista de usuarios)."""
    return {r[0] for r in conn.execute("SELECT user_id FROM mfa_factors WHERE confirmed = 1")}


def secrets(conn: Connection) -> list:
    """``(user_id, secret)`` de todas las semillas, para volver a cifrarlas con otra clave."""
    return conn.execute("SELECT user_id, secret FROM mfa_factors").fetchall()


def set_secret(conn: Connection, user_id: int, sealed_secret: str) -> None:
    conn.execute("UPDATE mfa_factors SET secret = ? WHERE user_id = ?", (sealed_secret, user_id))

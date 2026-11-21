"""Repositorio de la verificación en dos pasos (tablas ``mfa_factors``, ``mfa_passkeys`` y ``mfa_recovery``).

Los códigos de recuperación son de la cuenta, no de un factor: se conservan mientras quede alguno (la app de códigos o
una passkey) y se borran con el último.

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
    """Empieza (o vuelve a empezar) un alta de la app de códigos: una semilla nueva, sin confirmar. Sustituye la app
    anterior; los códigos de recuperación, solo si no hay passkeys que los sigan necesitando."""
    now = now_iso()
    if not passkey_count(conn, user_id):
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
    """Quita TODO: la app de códigos, las passkeys y los códigos de recuperación. Devuelve si había algo."""
    cur = conn.execute("DELETE FROM mfa_factors WHERE user_id = ?", (user_id,))
    keys = conn.execute("DELETE FROM mfa_passkeys WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM mfa_recovery WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0 or keys.rowcount > 0


def delete_totp(conn: Connection, user_id: int) -> bool:
    """Quita solo la app de códigos; los códigos de recuperación, si ya no queda ninguna passkey."""
    cur = conn.execute("DELETE FROM mfa_factors WHERE user_id = ?", (user_id,))
    _drop_recovery_if_alone(conn, user_id)
    conn.commit()
    return cur.rowcount > 0


def _drop_recovery_if_alone(conn: Connection, user_id: int) -> None:
    has_totp = conn.execute("SELECT 1 FROM mfa_factors WHERE user_id = ? AND confirmed = 1", (user_id,)).fetchone()
    if not has_totp and not passkey_count(conn, user_id):
        conn.execute("DELETE FROM mfa_recovery WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------------------- passkeys

def passkeys(conn: Connection, user_id: int) -> list:
    return conn.execute("SELECT * FROM mfa_passkeys WHERE user_id = ? ORDER BY created_at, id", (user_id,)).fetchall()


def passkey_count(conn: Connection, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM mfa_passkeys WHERE user_id = ?", (user_id,)).fetchone()[0]


def passkey(conn: Connection, user_id: int, credential_id: str):
    """La passkey de ESA cuenta con ese id (una credencial de otra cuenta no vale para esta)."""
    return conn.execute("SELECT * FROM mfa_passkeys WHERE user_id = ? AND credential_id = ?",
                        (user_id, credential_id)).fetchone()


def passkey_by_credential(conn: Connection, credential_id: str):
    """La passkey con ese id, sea de quien sea (entrar sin contraseña: la cuenta la dice la passkey), con el ``uid``
    de su cuenta para comprobar el ``userHandle``."""
    return conn.execute("SELECT p.*, u.uid AS user_uid FROM mfa_passkeys p JOIN users u ON u.id = p.user_id "
                        "WHERE p.credential_id = ?", (credential_id,)).fetchone()


def credential_taken(conn: Connection, credential_id: str) -> bool:
    return conn.execute("SELECT 1 FROM mfa_passkeys WHERE credential_id = ?", (credential_id,)).fetchone() is not None


def add_passkey(conn: Connection, user_id: int, *, credential_id: str, public_key: str, alg: int, sign_count: int,
                name: str, aaguid: str) -> int:
    cur = conn.execute("INSERT INTO mfa_passkeys (user_id, credential_id, public_key, alg, sign_count, name, aaguid, "
                       "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (user_id, credential_id, public_key, alg, sign_count, name, aaguid, now_iso()))
    conn.commit()
    return cur.lastrowid


def note_passkey_use(conn: Connection, passkey_id: int, last_count: int, new_count: int) -> bool:
    """Apunta el uso y el contador. Solo si el contador sigue siendo el que se comprobó: de dos aserciones a la vez
    con la misma credencial que lleva contador, una sola gana. Con contador 0 (sin contador) las dos casan aquí: lo
    que impide repetir una aserción es el challenge gastado (:func:`core.mfa.spend_challenge`), no esto."""
    cur = conn.execute("UPDATE mfa_passkeys SET sign_count = ?, last_used_at = ? WHERE id = ? AND sign_count = ?",
                       (new_count, now_iso(), passkey_id, last_count))
    conn.commit()
    return cur.rowcount == 1


def rename_passkey(conn: Connection, user_id: int, passkey_id: int, name: str) -> bool:
    cur = conn.execute("UPDATE mfa_passkeys SET name = ? WHERE id = ? AND user_id = ?", (name, passkey_id, user_id))
    conn.commit()
    return cur.rowcount == 1


def remove_passkey(conn: Connection, user_id: int, passkey_id: int) -> bool:
    """Quita una passkey de la cuenta; con la última (y sin app de códigos), también los códigos de recuperación."""
    cur = conn.execute("DELETE FROM mfa_passkeys WHERE id = ? AND user_id = ?", (passkey_id, user_id))
    _drop_recovery_if_alone(conn, user_id)
    conn.commit()
    return cur.rowcount == 1


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
    """Los ids de las cuentas con un factor activo, app o passkey (una consulta para toda una lista de usuarios)."""
    return {r[0] for r in conn.execute("SELECT user_id FROM mfa_factors WHERE confirmed = 1 "
                                       "UNION SELECT user_id FROM mfa_passkeys")}


def secrets(conn: Connection) -> list:
    """``(user_id, secret)`` de todas las semillas, para volver a cifrarlas con otra clave."""
    return conn.execute("SELECT user_id, secret FROM mfa_factors").fetchall()


def set_secret(conn: Connection, user_id: int, sealed_secret: str) -> None:
    conn.execute("UPDATE mfa_factors SET secret = ? WHERE user_id = ?", (sealed_secret, user_id))

"""Favoritos del explorador (tabla ``favorites``) y lo reciente de cada usuario (de ``audit_log``)."""
from __future__ import annotations

from sqlite3 import Connection

from ..connection import now_iso


def list_for_user(conn: Connection, user_id: int) -> list:
    return conn.execute("SELECT * FROM favorites WHERE user_id = ? ORDER BY is_dir DESC, LOWER(rel)",
                        (user_id,)).fetchall()


def is_favorite(conn: Connection, user_id: int, root: str, rel: str) -> bool:
    return conn.execute("SELECT 1 FROM favorites WHERE user_id = ? AND root = ? AND rel = ?",
                        (user_id, root, rel)).fetchone() is not None


def add(conn: Connection, user_id: int, root: str, rel: str, is_dir: bool) -> None:
    conn.execute("INSERT OR IGNORE INTO favorites (user_id, root, rel, is_dir, created_at) VALUES (?, ?, ?, ?, ?)",
                 (user_id, root, rel, 1 if is_dir else 0, now_iso()))
    conn.commit()


def remove(conn: Connection, user_id: int, root: str, rel: str) -> None:
    conn.execute("DELETE FROM favorites WHERE user_id = ? AND root = ? AND rel = ?", (user_id, root, rel))
    conn.commit()


def _owner_clause(user_id: int | None) -> tuple[str, tuple]:
    # En «home» la carpeta es de cada usuario: solo cambian los favoritos de quien hace la operación
    return ("", ()) if user_id is None else (" AND user_id = ?", (user_id,))


def moved(conn: Connection, root: str, old: str, new_root: str, new: str, user_id: int | None = None) -> None:
    """``old`` (y lo que haya dentro) pasa a ser ``new`` (en ``new_root``)."""
    owner, args = _owner_clause(user_id)
    conn.execute(f"""UPDATE OR IGNORE favorites SET root = ?, rel = ? || SUBSTR(rel, ?)
                     WHERE root = ? AND (rel = ? OR rel LIKE ? ESCAPE '\\'){owner}""",
                 (new_root, new, len(old) + 1, root, old, _like_prefix(old), *args))
    conn.execute(f"DELETE FROM favorites WHERE root = ? AND (rel = ? OR rel LIKE ? ESCAPE '\\'){owner}",
                 (root, old, _like_prefix(old), *args))   # los que chocaban con uno que ya había
    conn.commit()


def removed(conn: Connection, root: str, rel: str, user_id: int | None = None) -> None:
    """Se borró ``rel``: fuera sus favoritos y los de lo que tenía dentro."""
    owner, args = _owner_clause(user_id)
    conn.execute(f"DELETE FROM favorites WHERE root = ? AND (rel = ? OR rel LIKE ? ESCAPE '\\'){owner}",
                 (root, rel, _like_prefix(rel), *args))
    conn.commit()


def _like_prefix(rel: str) -> str:
    return rel.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"


def recent(conn: Connection, username: str, limit: int = 30) -> list:
    """Lo último que el usuario abrió, descargó, subió o editó desde la web: (target «root:/rel», cuándo, acción).
    Sin lo de la unidad de red ni lo hecho con tokens (la sincronización de VS Code lo llenaría)."""
    return conn.execute("""SELECT target, MAX(ts) AS ts, action FROM audit_log
                           WHERE username = ? AND action IN ('download', 'upload', 'edit') AND target LIKE '%:/%'
                             AND (detail IS NULL OR (detail NOT LIKE 'webdav%' AND detail NOT LIKE '%token=%'))
                           GROUP BY target ORDER BY MAX(ts) DESC LIMIT ?""", (username, limit)).fetchall()

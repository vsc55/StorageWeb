"""Repositorio de los enlaces para compartir (tabla ``share_links``, migración 006). Las reglas, en
``core/links.py``."""
from __future__ import annotations

import uuid
from sqlite3 import Connection

from ..connection import now_iso, owner_filter, subtree

_SELECT = """SELECT l.*, u.username AS owner, u.enabled AS owner_enabled
             FROM share_links l JOIN users u ON u.id = l.user_id"""


def create(conn: Connection, *, user_id: int, token_hash: str, token_enc: str, root: str, rel: str, is_dir: bool,
           mode: str, password_hash: str | None, expires_at: str | None, max_downloads: int | None,
           note: str | None) -> int:
    cur = conn.execute(
        """INSERT INTO share_links (uid, user_id, token_hash, token_enc, root, rel, is_dir, mode, password_hash,
                                    expires_at, max_downloads, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), user_id, token_hash, token_enc, root, rel, int(bool(is_dir)), mode, password_hash,
         expires_at, max_downloads, note, now_iso()))
    conn.commit()
    return int(cur.lastrowid)


def get_by_id(conn: Connection, link_id: int):
    return conn.execute(f"{_SELECT} WHERE l.id = ?", (link_id,)).fetchone()


def get_by_uid(conn: Connection, uid: str):
    return conn.execute(f"{_SELECT} WHERE l.uid = ?", (uid,)).fetchone()


def get_by_hash(conn: Connection, token_hash: str):
    return conn.execute(f"{_SELECT} WHERE l.token_hash = ?", (token_hash,)).fetchone()


def list_for_user(conn: Connection, user_id: int) -> list:
    return conn.execute(f"{_SELECT} WHERE l.user_id = ? ORDER BY l.created_at DESC, l.id DESC", (user_id,)).fetchall()


def list_all(conn: Connection) -> list:
    return conn.execute(f"{_SELECT} ORDER BY l.created_at DESC, l.id DESC").fetchall()


def delete(conn: Connection, link_id: int) -> None:
    conn.execute("DELETE FROM share_links WHERE id = ?", (link_id,))
    conn.commit()


def count_download(conn: Connection, link_id: int) -> bool:
    """Suma una descarga si quedan (``max_downloads``): False si ya no quedaban. Atómico: dos a la vez no pasan
    del máximo."""
    cur = conn.execute("""UPDATE share_links SET downloads = downloads + 1, last_used_at = ?
                          WHERE id = ? AND (max_downloads IS NULL OR downloads < max_downloads)""",
                       (now_iso(), link_id))
    conn.commit()
    return cur.rowcount == 1


def count_upload(conn: Connection, link_id: int) -> None:
    conn.execute("UPDATE share_links SET uploads = uploads + 1, last_used_at = ? WHERE id = ?", (now_iso(), link_id))
    conn.commit()


def touch(conn: Connection, link_id: int) -> None:
    conn.execute("UPDATE share_links SET last_used_at = ? WHERE id = ?", (now_iso(), link_id))
    conn.commit()


def moved(conn: Connection, root: str, old: str, new_root: str, new: str, user_id: int | None = None) -> None:
    """``old`` (y lo que haya dentro) pasa a ser ``new`` (en ``new_root``). Con ``user_id``, solo los suyos."""
    owner, args = owner_filter(user_id)
    inside, paths = subtree("rel", old)
    conn.execute(f"UPDATE share_links SET root = ?, rel = ? || SUBSTR(rel, ?) WHERE root = ? AND {inside}{owner}",
                 (new_root, new, len(old) + 1, root, *paths, *args))
    conn.commit()


def matching(conn: Connection, root: str, rel: str, user_id: int | None = None) -> list:
    """Los enlaces activos (sin quitar) de ``rel`` y de lo que tiene dentro."""
    owner, args = owner_filter(user_id, "l.user_id")
    inside, paths = subtree("l.rel", rel)
    return conn.execute(f"{_SELECT} WHERE l.revoked_at IS NULL AND l.root = ? AND {inside}{owner}",
                        (root, *paths, *args)).fetchall()


def revoke(conn: Connection, link_id: int, by: str | None, reason: str) -> None:
    """Lo deja de compartir sin borrarlo: deja de funcionar y conserva su historial."""
    conn.execute("UPDATE share_links SET revoked_at = ?, revoked_by = ?, revoke_reason = ? WHERE id = ? "
                 "AND revoked_at IS NULL", (now_iso(), by, reason, link_id))
    conn.commit()


def purge_old(conn: Connection, before: str) -> int:
    """Borra los quitados o caducados antes de ``before`` (ISO). Su historial (share_link_events) se queda."""
    cur = conn.execute("""DELETE FROM share_links WHERE (revoked_at IS NOT NULL AND revoked_at < ?)
                          OR (expires_at IS NOT NULL AND expires_at < ?)""", (before, before))
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- historial (share_link_events)

def log_event(conn: Connection, link, event: str, *, path: str | None = None, ip: str | None = None,
              user_agent: str | None = None, detail: str | None = None) -> None:
    conn.execute("""INSERT INTO share_link_events (link_uid, owner, target, event, path, ip, user_agent, detail, at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (link["uid"], link["owner"], f"{link['root']}:/{link['rel']}", event, path, ip,
                  (user_agent or "")[:400] or None, detail, now_iso()))
    conn.commit()


def events(conn: Connection, link_uid: str, limit: int = 2000) -> list:
    return conn.execute("SELECT * FROM share_link_events WHERE link_uid = ? ORDER BY at DESC, id DESC LIMIT ?",
                        (link_uid, limit)).fetchall()


def summary(conn: Connection, uids: list[str]) -> dict[str, dict]:
    """``{uid: {"opened", "downloads", "uploads", "refused", "last"}}`` de varios enlaces (``last``: el último
    acceso de alguien de fuera, ISO)."""
    out: dict[str, dict] = {}
    if not uids:
        return out
    marks = ",".join("?" * len(uids))
    for uid, event, n, last in conn.execute(
            f"""SELECT link_uid, event, COUNT(*), MAX(at) FROM share_link_events WHERE link_uid IN ({marks})
                GROUP BY link_uid, event""", uids):
        row = out.setdefault(uid, {"opened": 0, "downloads": 0, "uploads": 0, "refused": 0, "last": ""})
        key = {"download": "downloads", "zip": "downloads", "upload": "uploads"}.get(event, event)
        if key in ("opened", "downloads", "uploads", "refused"):
            row[key] += n
        if event not in ("created", "revoked") and last > row["last"]:
            row["last"] = last
    return out


def deleted_history(conn: Connection, owner: str | None = None) -> list:
    """Los enlaces que ya no existen (la limpieza borró su fila) pero conservan historial: uno por enlace, con su
    dueño, lo que compartía, el primer y el último suceso y cuántos hay. Con ``owner``, solo los suyos."""
    where = " AND owner = ?" if owner else ""
    args = (owner,) if owner else ()
    return conn.execute(f"""SELECT link_uid, MAX(owner) AS owner, MAX(target) AS target, MIN(at) AS first_at,
                                   MAX(at) AS last_at, COUNT(*) AS events
                            FROM share_link_events
                            WHERE link_uid NOT IN (SELECT uid FROM share_links){where}
                            GROUP BY link_uid ORDER BY MAX(at) DESC""", args).fetchall()


def purge_events(conn: Connection, before: str) -> int:
    cur = conn.execute("DELETE FROM share_link_events WHERE at < ?", (before,))
    conn.commit()
    return cur.rowcount

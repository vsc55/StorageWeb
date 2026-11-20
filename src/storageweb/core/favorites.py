"""Favoritos y recientes del explorador.

- **Favoritos**: carpetas o archivos que el usuario marca con la estrella (tabla ``favorites``). Solo se muestran
  los de carpetas de StorageWeb a las que sigue teniendo acceso. Si se renombra, mueve o borra algo desde StorageWeb
  (web o unidad de red), :func:`moved` y :func:`deleted` los mantienen al día; lo que cambie por fuera queda como
  estaba (y lleva a «no encontrado»).
- **Recientes**: lo último que el usuario abrió, descargó o subió desde la web, sacado de la auditoría.
"""
from __future__ import annotations

from sqlite3 import Connection

from ..db.repositories import favorites as repo
from . import backends, storage

HOME = "home"


def _roots(user, cfg: dict) -> dict[str, dict]:
    return {r["name"]: r for r in storage.available_roots(user, cfg)}


def listing(conn: Connection, user, cfg: dict) -> list[dict]:
    """Los favoritos del usuario en las carpetas a las que tiene acceso, listos para mostrar."""
    roots = _roots(user, cfg)
    out = []
    for row in repo.list_for_user(conn, user["id"]):
        root = roots.get(row["root"])
        if root is None or storage.is_hidden(cfg, row["rel"]):
            continue
        out.append({"root": row["root"], "root_label": root["label"], "rel": row["rel"], "is_dir": bool(row["is_dir"]),
                    "name": backends.name_of(row["rel"]) if row["rel"] else root["label"]})
    return out


def keys(conn: Connection, user) -> set[tuple[str, str]]:
    """``{(root, rel)}`` de los favoritos del usuario, para marcar las estrellas."""
    return {(r["root"], r["rel"]) for r in repo.list_for_user(conn, user["id"])}


def toggle(conn: Connection, user, root: str, rel: str, is_dir: bool) -> bool:
    """Añade o quita un favorito; devuelve si queda como favorito."""
    if repo.is_favorite(conn, user["id"], root, rel):
        repo.remove(conn, user["id"], root, rel)
        return False
    repo.add(conn, user["id"], root, rel, is_dir)
    return True


def remove(conn: Connection, user, root: str, rel: str) -> None:
    """Quita un favorito del usuario (la X de la lista), exista o no todavía lo que señala."""
    repo.remove(conn, user["id"], root, rel)


def recent(conn: Connection, user, cfg: dict, limit: int = 30) -> list[dict]:
    """Lo último abierto, descargado o subido desde la web, en carpetas a las que el usuario sigue teniendo
    acceso: ``{root, root_label, rel, name, folder, ts, action}``."""
    roots = _roots(user, cfg)
    out = []
    for row in repo.recent(conn, user["username"], limit * 2):
        name, _sep, rel = row["target"].partition(":/")
        root = roots.get(name)
        if root is None or not rel or storage.is_hidden(cfg, rel):
            continue
        out.append({"root": name, "root_label": root["label"], "rel": rel, "name": backends.name_of(rel),
                    "folder": backends.parent_rel(rel), "ts": row["ts"], "action": row["action"]})
        if len(out) >= limit:
            break
    return out


def _owner(user, *roots: str) -> int | None:
    # La carpeta personal es de cada usuario: sus favoritos solo cambian para quien hace la operación
    return user["id"] if HOME in roots else None


def moved(conn: Connection, user, root: str, rel: str, new_root: str, new_rel: str) -> None:
    repo.moved(conn, root, rel, new_root, new_rel, _owner(user, root, new_root))


def deleted(conn: Connection, user, root: str, rel: str) -> None:
    repo.removed(conn, root, rel, _owner(user, root))

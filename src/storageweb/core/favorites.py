"""Favoritos y recientes del explorador.

- **Favoritos**: carpetas o archivos que el usuario marca con la estrella (tabla ``favorites``). Solo se muestran
  los de carpetas de StorageWeb a las que sigue teniendo acceso. Si se renombra, mueve o borra algo desde StorageWeb
  (web o unidad de red), :func:`moved` y :func:`deleted` los mantienen al día; lo que cambie por fuera queda como
  estaba (y lleva a «no encontrado»).
- **Recientes**: lo último que el usuario abrió, descargó o subió desde la web, sacado de la auditoría.
- **Desde la administración** (la ficha del usuario): verlos todos, también los que ya no le sirven (sin acceso u
  ocultos), quitarlos y añadirle uno (:func:`for_admin`, :func:`add_for`, :func:`clear`).
"""
from __future__ import annotations

from sqlite3 import Connection

from ..db.repositories import favorites as repo
from ..i18n import _
from . import backends, storage
from ..settings.errors import UserError



def _roots(user, cfg: dict) -> dict[str, dict]:
    return {r["name"]: r for r in storage.available_roots(user, cfg)}


def listing(conn: Connection, user, cfg: dict) -> list[dict]:
    """Los favoritos del usuario en las carpetas a las que tiene acceso, listos para mostrar (los ``ok`` de
    :func:`for_admin`)."""
    return [item for item in for_admin(conn, user, cfg) if item["state"] == "ok"]


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


class FavoriteError(UserError):
    """No se puede añadir ese favorito. ``message`` es para quien lo intentó."""


def for_admin(conn: Connection, user, cfg: dict) -> list[dict]:
    """TODOS los favoritos del usuario para la administración, también los que ya no ve: ``state`` es ``ok``,
    ``no_access`` (la carpeta de StorageWeb ya no es suya) u ``hidden`` (lo oculta ``storage.hidden``)."""
    roots = _roots(user, cfg)
    out = []
    for row in repo.list_for_user(conn, user["id"]):
        root = roots.get(row["root"])
        state = "no_access" if root is None else "hidden" if storage.is_hidden(cfg, row["rel"]) else "ok"
        out.append({"root": row["root"], "root_label": root["label"] if root else row["root"], "rel": row["rel"],
                    "is_dir": bool(row["is_dir"]), "state": state, "created_at": row["created_at"],
                    "name": backends.name_of(row["rel"]) if row["rel"] else (root["label"] if root else row["root"])})
    return out


def add_for(conn: Connection, user, cfg: dict, root_name: str, path: str) -> dict:
    """Añade a ``user`` un favorito en una de SUS carpetas (``root_name``) que exista. Lanza :class:`FavoriteError`."""
    root = _roots(user, cfg).get(str(root_name or ""))
    if root is None:
        raise FavoriteError(_("That folder is not one of the user's."))
    try:
        rel, entry = storage.existing_entry(cfg, root, str(path or "").strip().strip("/"))
    except storage.EntryError as exc:
        raise FavoriteError(exc.message) from exc
    if entry is None:
        raise FavoriteError(_("«%(path)s» does not exist in %(folder)s.", path=rel or "/", folder=root["label"]))
    repo.add(conn, user["id"], root["name"], rel, entry.is_dir)
    return {"root": root["name"], "rel": rel, "is_dir": entry.is_dir}


def clear(conn: Connection, user) -> int:
    """Quita todos los favoritos del usuario; devuelve cuántos tenía."""
    return repo.remove_all(conn, user["id"])


def moved(conn: Connection, user, root: str, rel: str, new_root: str, new_rel: str) -> None:
    repo.moved(conn, root, rel, new_root, new_rel, storage.home_owner(user, root, new_root))


def deleted(conn: Connection, user, root: str, rel: str) -> None:
    repo.removed(conn, root, rel, storage.home_owner(user, root))

"""Raíces de almacenamiento (home + carpetas compartidas) y operaciones de directorio."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ..db.repositories.users import groups_of
from ..i18n import _, format_datetime, format_size
from .groups import ADMINS_GROUP
from .permissions import ADMIN
from .security import UPLOAD_TMP_PREFIX, safe_username_for_path


class RootNotFound(Exception):
    pass


def home_path_for(user, cfg: dict) -> Path:
    if user["home_path"]:
        return Path(user["home_path"])
    tmpl = cfg["storage"]["home_template"]
    return Path(tmpl.replace("{username}", safe_username_for_path(user["username"])))


def available_roots(user, cfg: dict) -> list[dict]:
    """Raíces accesibles: su home + las carpetas compartidas permitidas por usuario o grupo."""
    roots = [{"name": "home", "label": _("My folder"), "path": home_path_for(user, cfg), "read_only": False}]
    uname = user["username"].lower()
    ugroups = groups_of(user)
    if user["role"] == ADMIN:
        ugroups.add(ADMINS_GROUP)  # grupo de serie: lo da el rol
    for share in cfg["storage"]["shares"]:
        by_user = "*" in share["users"] or uname in share["users"]
        matched = ugroups.intersection(share["groups"])
        if not (by_user or matched):
            continue
        # Solo lectura si lo es la carpeta o si todos los grupos por los que entra son de solo lectura
        read_only = share["read_only"] or (not by_user and matched <= set(share.get("read_only_groups", [])))
        roots.append({**share, "path": Path(share["path"]), "read_only": read_only})
    return roots


def explain_access(user, cfg: dict, group_labels: dict[str, str] | None = None) -> list[dict]:
    """Carpetas que ve el usuario, con su nivel (``read``/``write``) y por qué.

    Usa las mismas reglas que :func:`available_roots`; ``group_labels`` traduce identificadores de
    grupo (o Object IDs) a su nombre visible.
    """
    labels = group_labels or {}
    uname = user["username"].lower()
    ugroups = groups_of(user)
    if user["role"] == ADMIN:
        ugroups.add(ADMINS_GROUP)
    result = [{"name": "home", "label": _("My folder"), "level": "write", "reasons": [_("personal folder")]}]
    for root in available_roots(user, cfg)[1:]:
        share = next(s for s in cfg["storage"]["shares"] if s["name"] == root["name"])
        reasons = []
        if "*" in share["users"]:
            reasons.append(_("open to all users"))
        if uname in share["users"]:
            reasons.append(_("by user name"))
        for ref in sorted(ugroups.intersection(share["groups"])):
            reasons.append(_("group %(name)s", name=labels.get(ref, ref)))
        if share["read_only"]:
            reasons.append(_("read-only folder"))
        result.append({"name": root["name"], "label": root["label"],
                       "level": "read" if root["read_only"] else "write", "reasons": reasons})
    return result


def find_root(user, cfg: dict, name: str) -> dict:
    for root in available_roots(user, cfg):
        if root["name"] != name:
            continue
        path = root["path"]
        if not path.exists():
            storage = cfg["storage"]
            create = storage["create_home"] if name == "home" else storage["create_shares"]
            if not create:
                raise RootNotFound(_("The configured folder does not exist on the server."))
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o750 if name == "home" else 0o770)
            except OSError:
                pass
        return root
    raise RootNotFound("")


def rel_path(root: dict, target: Path) -> str:
    rel = target.relative_to(root["path"].resolve())
    return "" if str(rel) == "." else rel.as_posix()


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(1, 10000):
        candidate = directory / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(name)


SORT_KEYS = ("name", "size", "mtime")


def list_directory(root: dict, target: Path, show_hidden: bool, sort: str = "name",
                   descending: bool = False) -> list[dict]:
    """Contenido de una carpeta: las carpetas siempre primero, luego ordenado por ``sort``."""
    base_rel = rel_path(root, target)
    entries = []
    with os.scandir(target) as it:
        for entry in it:
            if entry.name.startswith(UPLOAD_TMP_PREFIX):
                continue
            if not show_hidden and entry.name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir()
                st = entry.stat()
            except OSError:
                continue
            ext = "" if is_dir else Path(entry.name).suffix.lstrip(".").upper()
            entries.append({
                "name": entry.name,
                "is_dir": is_dir,
                "ext": ext if len(ext) <= 8 else "",
                "bytes": 0 if is_dir else st.st_size,
                "ts": st.st_mtime,
                "size": "" if is_dir else format_size(st.st_size),
                "mtime": format_datetime(datetime.fromtimestamp(st.st_mtime)),
                "rel": f"{base_rel}/{entry.name}".lstrip("/"),
            })
    if sort not in SORT_KEYS:
        sort = "name"
    keys = {"name": lambda e: e["name"].lower(), "size": lambda e: e["bytes"], "mtime": lambda e: e["ts"]}
    entries.sort(key=lambda e: (e["name"].lower(),))  # desempate estable por nombre
    entries.sort(key=keys[sort], reverse=descending)
    entries.sort(key=lambda e: not e["is_dir"])        # carpetas primero (sort estable)
    return entries


def breadcrumbs(rel: str) -> list[dict]:
    crumbs, acc = [], []
    for part in rel.split("/") if rel else []:
        acc.append(part)
        crumbs.append({"name": part, "rel": "/".join(acc)})
    return crumbs

"""Raíces de almacenamiento (home + carpetas compartidas) y operaciones de directorio."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ..db.repositories.users import groups_of
from ..i18n import _, format_datetime, format_size
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
    for share in cfg["storage"]["shares"]:
        if "*" in share["users"] or uname in share["users"] or ugroups.intersection(share["groups"]):
            roots.append({**share, "path": Path(share["path"])})
    return roots


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


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def list_directory(root: dict, target: Path, show_hidden: bool) -> list[dict]:
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
            entries.append({
                "name": entry.name,
                "is_dir": is_dir,
                "size": "" if is_dir else format_size(st.st_size),
                "mtime": format_datetime(datetime.fromtimestamp(st.st_mtime)),
                "rel": f"{base_rel}/{entry.name}".lstrip("/"),
            })
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return entries


def breadcrumbs(rel: str) -> list[dict]:
    crumbs, acc = [], []
    for part in rel.split("/") if rel else []:
        acc.append(part)
        crumbs.append({"name": part, "rel": "/".join(acc)})
    return crumbs

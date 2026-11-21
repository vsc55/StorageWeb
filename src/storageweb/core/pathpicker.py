"""El selector de rutas de la administración (botón *Examinar* y autocompletado de los campos de ruta): el contenido
de una carpeta en uno de tres sitios, según a qué mira el campo.

* ``root``: una carpeta de StorageWeb de una persona (su carpeta personal o una compartida suya): rutas relativas a
  ella, con los «ocultos para todos» fuera, como los ve ella. Los favoritos.
* ``location``: una ubicación de almacenamiento (S3, SMB…), rutas relativas a ella. Las carpetas compartidas, las
  personales y las copias fuera del servidor que van en una.
* ``disk``: el disco del servidor, rutas absolutas y LOCALES, solo carpetas. Las carpetas compartidas y personales
  en el disco. Solo nombres, y solo para administradores: no da más de lo que ya pueden (una carpeta compartida puede
  apuntar a cualquier ruta del servidor) y, con ``storage.allowed_folders``, solo dentro de ellas. Nunca rutas de red
  (:func:`network_path`): el servidor se conectaría a otro equipo con su cuenta.

Las rutas relativas (``root``, ``location``) pasan por ``backends.clean_rel`` y el backend (``resolve_inside`` en el
disco: tampoco se sale siguiendo un enlace simbólico), como en el explorador.

Nada lanza: un error es ``error`` en la respuesta (una carpeta sin permiso, una ubicación caída). Sin Flask.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .. import patterns
from ..settings import server_paths
from ..settings.server_paths import network_path
from ..i18n import _
from . import backends, storage
from .security import PathError

MAX_ENTRIES = 500       # una carpeta con más: las primeras, y lo dice (``truncated``)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _answer(path: str, parent: str | None, entries: list[dict], error: str = "") -> dict:
    truncated = len(entries) > MAX_ENTRIES
    return {"path": path, "parent": parent, "entries": entries[:MAX_ENTRIES], "truncated": truncated,
            "error": error}


def _parent_rel(rel: str) -> str | None:
    return None if not rel else ("/".join(rel.split("/")[:-1]))


def browse_root(cfg: dict, root: dict, rel: str, files: bool = True) -> dict:
    """El contenido de ``rel`` dentro de ``root`` (una raíz de :func:`core.storage.available_roots`)."""
    try:
        rel = backends.clean_rel(str(rel or "").strip("/"))
    except PathError:
        return _answer("", None, [], _("That path is not valid."))
    if storage.is_hidden(cfg, rel):
        return _answer("", None, [], _("That path is hidden for everyone (Hidden for everyone)."))
    try:
        listing = storage.list_directory(root, rel, cfg["storage"]["show_hidden"], hidden=patterns.of(cfg))
    except FileNotFoundError:
        return _answer(rel, _parent_rel(rel), [], _("That folder does not exist."))
    except (PermissionError, backends.BackendError) as exc:
        return _answer(rel, _parent_rel(rel), [], getattr(exc, "message", "") or _("That folder cannot be read."))
    entries = [{"name": e["name"], "path": e["rel"], "is_dir": e["is_dir"]} for e in listing
               if files or e["is_dir"]]
    return _answer(rel, _parent_rel(rel), entries)


def browse_location(cfg: dict, location: str, rel: str) -> dict:
    """Las carpetas de ``rel`` dentro de la ubicación ``location``."""
    if not backends.find_location(cfg, location):
        return _answer("", None, [], _("The storage location %(name)s does not exist.", name=location))
    root = storage.make_root(cfg, "pick", location, location, "")
    return browse_root(cfg, root, rel, files=False)


def _top(allowed: list[str], error: str = "") -> dict:
    """Con varias carpetas permitidas, el principio: ellas mismas (las que existen; las de red no se listan)."""
    entries = [{"name": base, "path": base, "is_dir": True} for base in allowed
               if not network_path(base) and os.path.isdir(base)]
    return {**_answer("", None, entries, error), "top": True}


def browse_disk(path: str, start: str = "", allowed: list[str] | None = None) -> dict:
    """Las carpetas de ``path`` en el disco del servidor (absoluta y local; vacía = ``start``). Solo carpetas y solo
    nombres. Con ``allowed`` (``storage.allowed_folders``), solo dentro de ellas: fuera (también siguiendo un enlace
    simbólico), el principio (:func:`_top`) o la única que hay."""
    allowed = list(allowed or [])
    typed = str(path or "").strip()
    raw = typed or str(start or "").strip()
    if not raw:
        if not allowed:
            raw = os.getcwd()
        elif len(allowed) == 1:
            raw = allowed[0]
        else:
            return _top(allowed)
    if network_path(raw):
        return _answer("", None, [], _("Only folders of this server: network paths are not listed."))
    if _CONTROL.search(raw):
        return _answer("", None, [], _("That path is not valid."))
    if not os.path.isabs(raw):
        return _answer("", None, [], _("Write an absolute path (it starts with / or a drive letter)."))
    current = Path(os.path.abspath(raw))
    # Si la carpeta aún no existe (una carpeta personal nueva), se enseña la primera que sí, hacia arriba
    while not current.is_dir() and current.parent != current:
        current = current.parent
    base = server_paths.base_of(str(current), allowed) if allowed else None
    if allowed and base is None:
        # Fuera: lo que se escribió lo dice; el punto de partida (la base de las carpetas personales) no
        outside = _("Outside the allowed server folders: only what is inside them is listed.") if typed else ""
        if len(allowed) == 1 and not network_path(allowed[0]) and os.path.isdir(allowed[0]) and not typed:
            return browse_disk(allowed[0], allowed=allowed)
        return _top(allowed, outside)
    parent = None if current.parent == current else str(current.parent)
    if base is not None and server_paths.real(str(current)) == server_paths.real(base):
        parent = "" if len(allowed) > 1 else None        # más arriba solo está el principio (o nada)
    entries = []
    try:
        with os.scandir(current) as found:
            for entry in found:
                try:
                    if not entry.is_dir():
                        continue
                    full = str(current / entry.name)
                    if allowed and entry.is_symlink() and not server_paths.allowed_path(full, allowed):
                        continue                          # un enlace que sale de las permitidas
                    entries.append({"name": entry.name, "path": full, "is_dir": True})
                except OSError:
                    continue
    except OSError:
        return _answer(str(current), parent, [], _("That folder cannot be read."))
    entries.sort(key=lambda e: e["name"].lower())
    return _answer(str(current), parent, entries)

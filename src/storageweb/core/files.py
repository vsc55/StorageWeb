"""Operaciones sobre varios archivos: mover y copiar, descargar como ZIP y buscar por nombre.

Funcionan sobre cualquier almacenamiento (disco, S3, SMB…) a través de los backends de cada carpeta, y
respetan lo oculto para todos (``storage.hidden``). Los permisos los comprueba quien llama (la web).
"""
from __future__ import annotations

import time
import unicodedata
import zipfile
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator

from .. import patterns
from ..i18n import _
from . import backends, storage
from .security import UPLOAD_TMP_PREFIX, PathError

CHUNK = 1024 * 1024


class FilesError(Exception):
    """Algo que no se puede hacer con un elemento concreto (el mensaje es para el usuario)."""


# --------------------------------------------------------------------------- mover y copiar

def transfer(cfg: dict, src_root: dict, rel: str, dst_root: dict, dst_dir: str, *, move: bool) -> str:
    """Mueve o copia ``rel`` (archivo o carpeta) dentro de la carpeta ``dst_dir`` de ``dst_root``, con el mismo
    nombre. Nunca sobrescribe: si ya existe, :class:`FilesError`. Devuelve la ruta nueva."""
    rel = backends.clean_rel(rel)
    dst_dir = backends.clean_rel(dst_dir)
    if not rel:
        raise FilesError(_("A whole folder of StorageWeb cannot be moved or copied."))
    name = backends.name_of(rel)
    dst_rel = backends.join_rel(dst_dir, name)
    same = src_root["name"] == dst_root["name"]
    if storage.is_hidden(cfg, rel) or src_root["backend"].stat(rel) is None:
        raise FilesError(_("«%(name)s» no longer exists.", name=name))
    storage.check_visible_name(cfg, dst_rel)  # ValueError si el destino estaría oculto
    if same and move and backends.parent_rel(rel) == dst_dir:
        raise FilesError(_("«%(name)s» is already in that folder.", name=name))
    if same and (dst_dir == rel or dst_dir.startswith(rel + "/")):
        raise FilesError(_("«%(name)s» cannot be moved or copied into itself.", name=name))
    if not dst_root["backend"].is_dir(dst_dir):
        raise FilesError(_("The destination folder does not exist."))
    if dst_root["backend"].stat(dst_rel) is not None:
        raise FilesError(_("«%(name)s» already exists in the destination folder.", name=name))
    try:
        if move and same:
            src_root["backend"].move(rel, dst_rel)
        else:
            backends.copy_between(src_root["backend"], rel, dst_root["backend"], dst_rel)
            if move:
                src_root["backend"].delete(rel)
    except FileExistsError as exc:
        raise FilesError(_("«%(name)s» already exists in the destination folder.", name=name)) from exc
    except (backends.BackendError, OSError) as exc:
        reason = exc.message if isinstance(exc, backends.BackendError) else (exc.strerror or str(exc))
        message = (_("Could not move «%(name)s»: %(error)s", name=name, error=reason) if move
                   else _("Could not copy «%(name)s»: %(error)s", name=name, error=reason))
        raise FilesError(message) from exc
    return dst_rel


# --------------------------------------------------------------------------- ZIP

# Ya comprimidos: se guardan tal cual (comprimirlos otra vez solo gasta CPU)
_STORED = {"zip", "gz", "tgz", "bz2", "xz", "zst", "7z", "rar", "jpg", "jpeg", "png", "gif", "webp", "heic", "avif",
           "mp3", "mp4", "m4a", "m4v", "mov", "mkv", "avi", "webm", "ogg", "opus", "flac", "aac", "pdf", "docx",
           "xlsx", "pptx", "odt", "ods", "odp", "epub", "jar", "apk", "whl", "msi", "dmg", "iso"}


class _Pipe:
    """Destino del ZipFile que no admite seek: lo escrito se va sacando por trozos (streaming)."""

    def __init__(self):
        self.parts: deque[bytes] = deque()

    def write(self, data) -> int:
        if data:
            self.parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        out = b"".join(self.parts)
        self.parts.clear()
        return out


def _walk_files(cfg: dict, root: dict, rel: str, base: str):
    """(ruta en el almacenamiento, nombre dentro del ZIP, mtime) de cada archivo bajo ``rel``, como se ven en la
    web (sin lo oculto para todos ni, si la web los oculta, los que empiezan por punto)."""
    hidden = patterns.of(cfg)
    show_dot = cfg["storage"]["show_hidden"]
    entry = root["backend"].stat(rel) if rel else None  # la raíz de la carpeta de StorageWeb no tiene entrada
    if rel and entry is None:
        return
    if entry is not None and not entry.is_dir:
        yield rel, base, entry.mtime
        return
    yield None, base + "/", entry.mtime if entry else 0  # la carpeta, también vacía
    pending = [(rel, base)]
    while pending:
        dir_rel, dir_base = pending.pop()
        for child in storage.list_directory(root, dir_rel, show_dot, hidden=hidden):
            arc = f"{dir_base}/{child['name']}"
            if child["is_dir"]:
                yield None, arc + "/", child["ts"]
                pending.append((child["rel"], arc))
            else:
                yield child["rel"], arc, child["ts"]


def zip_stream(cfg: dict, items: list[tuple[dict, str]]) -> Iterator[bytes]:
    """El ZIP de esos elementos (archivos o carpetas enteras), generado mientras se descarga: sin archivo
    temporal y sin límite de tamaño (ZIP64). ``items``: (carpeta de StorageWeb, ruta)."""
    pipe = _Pipe()
    with zipfile.ZipFile(pipe, "w", allowZip64=True) as zf:
        used: set[str] = set()
        for root, rel in items:
            base = backends.name_of(rel) or str(root.get("label") or root["name"])
            name, n = base, 1
            while name in used:  # dos elementos con el mismo nombre (de carpetas distintas)
                n += 1
                name = f"{base} ({n})"
            used.add(name)
            for src_rel, arc, mtime in _walk_files(cfg, root, rel, name):
                date = time.localtime(mtime or time.time())[:6]
                info = zipfile.ZipInfo(arc, date_time=date if date[0] >= 1980 else (1980, 1, 1, 0, 0, 0))
                if src_rel is None:
                    info.external_attr = 0o40755 << 16 | 0x10
                    zf.writestr(info, b"")
                else:
                    ext = arc.rsplit(".", 1)[-1].lower() if "." in arc else ""
                    info.compress_type = zipfile.ZIP_STORED if ext in _STORED else zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    src, _size, _mtime = root["backend"].open(src_rel)
                    try:
                        with zf.open(info, "w", force_zip64=True) as dst:
                            while True:
                                chunk = src.read(CHUNK)
                                if not chunk:
                                    break
                                dst.write(chunk)
                                if len(pipe.parts) > 4:
                                    yield pipe.take()
                    finally:
                        src.close()
                yield pipe.take()
    yield pipe.take()


def zip_name(items: list[tuple[dict, str]]) -> str:
    """«informe.zip» para un solo elemento; «StorageWeb-AAAAMMDD-HHMM.zip» para varios."""
    if len(items) == 1:
        root, rel = items[0]
        return f"{backends.name_of(rel) or root.get('label') or root['name']}.zip"
    return time.strftime("StorageWeb-%Y%m%d-%H%M.zip")


# --------------------------------------------------------------------------- buscar

def _fold(text: str) -> str:
    """Sin mayúsculas ni tildes: «Informe Año» → «informe ano»."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def filter_by_name(entries: list[dict], query: str) -> list[dict]:
    """Las entradas de un listado cuyo nombre contiene todas las palabras de ``query`` (como :func:`search`, sin
    distinguir mayúsculas ni tildes); el filtro del explorador en una carpeta que no se muestra entera."""
    words = [_fold(w) for w in query.split() if w.strip()]
    if not words:
        return entries
    return [e for e in entries if all(w in _fold(e["name"]) for w in words)]


@dataclass
class SearchResult:
    items: list[dict] = field(default_factory=list)
    truncated: bool = False      # se paró antes de recorrerlo todo (límite de resultados, tiempo o carpetas)
    folders_scanned: int = 0


def search(cfg: dict, places: list[tuple[dict, str]], query: str, *, limit: int = 200, seconds: float = 8.0,
           max_folders: int = 20000) -> SearchResult:
    """Archivos y carpetas cuyo nombre contiene todas las palabras de ``query`` (sin distinguir mayúsculas ni
    tildes), bajo esos sitios: (carpeta de StorageWeb, ruta desde la que buscar; "" = toda). Se para al llegar a
    ``limit`` resultados, ``seconds`` segundos o ``max_folders`` carpetas recorridas (en un almacenamiento remoto
    cada carpeta es una petición)."""
    words = [_fold(w) for w in query.split() if w.strip()]
    result = SearchResult()
    if not words:
        return result
    hidden = patterns.of(cfg)
    show_dot = cfg["storage"]["show_hidden"]
    deadline = time.monotonic() + seconds
    for root, start in places:
        pending = [backends.clean_rel(start)]
        while pending:
            if len(result.items) >= limit or time.monotonic() > deadline or result.folders_scanned >= max_folders:
                result.truncated = True
                return result
            dir_rel = pending.pop()
            result.folders_scanned += 1
            try:
                children = storage.list_directory(root, dir_rel, show_dot, hidden=hidden)
            except (backends.BackendError, PermissionError, OSError, PathError):
                continue  # una carpeta que no se puede leer no para la búsqueda
            for child in children:
                if child["name"].startswith(UPLOAD_TMP_PREFIX):
                    continue
                if child["is_dir"]:
                    pending.append(child["rel"])
                folded = _fold(child["name"])
                if all(w in folded for w in words):
                    result.items.append({"root": root, "rel": child["rel"], "name": child["name"],
                                         "is_dir": child["is_dir"], "size": child["size"], "bytes": child["bytes"],
                                         "mtime": child["mtime"], "ts": child["ts"],
                                         "folder": backends.parent_rel(child["rel"])})
                    if len(result.items) >= limit:
                        result.truncated = True
                        return result
    return result

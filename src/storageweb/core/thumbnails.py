"""Miniaturas de las imágenes para el explorador (``preview.thumbnails``): las genera el servidor con Pillow (una
dependencia opcional: ``pip install storageweb[thumbnails]``; sin ella, el explorador enseña iconos) y las guarda
en ``<data_dir>/thumbnails``, nunca en la carpeta de nadie.

* **Qué**: solo las imágenes que abre el visor (``preview.kind_of`` = ``image``, con sus ajustes) y cuyo formato
  tiene decodificador en ``core/media_types.json`` (``image.thumbnails``: extensión → formato de Pillow). Pillow
  abre el archivo SOLO con ese formato (``formats=``): un archivo que dice ser .png y no lo es no se intenta
  decodificar como otra cosa. Nunca SVG ni nada que no sea una imagen.
* **Límites**: el original, como mucho ``preview.thumbnail_max_mb``; como mucho :data:`MAX_PIXELS` píxeles (las
  «bombas de descompresión» de Pillow son un error, no un aviso); :data:`WORKERS` generaciones a la vez (las demás
  esperan su turno o, pasado :data:`WAIT_SECONDS`, contestan «ocupado»).
* **Caché**: la clave es la carpeta de StorageWeb (``root["where"]``), la ruta, el tamaño y la fecha: un archivo
  que cambia tiene otra miniatura y la vieja se va con la limpieza (tarea ``thumbnail_cleanup``: las que nadie pide
  desde :data:`UNUSED_DAYS` días y, si pasan de ``preview.thumbnail_cache_mb``, las menos usadas).

Sin Flask. Las miniaturas no se auditan (el explorador pide decenas al abrir una carpeta; ver un archivo sí).
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import warnings
from pathlib import Path

from ..i18n import _
from . import backends, maintenance, preview
from ..settings.errors import UserError
from ..fsutil import atomic_write

log = logging.getLogger(__name__)

SIZE = 256                 # lado máximo (px): nítida a 128 px en pantallas de doble densidad
MAX_PIXELS = 80_000_000    # una foto de 80 Mpx; más grande, sin miniatura (y Pillow no la llega a decodificar)
WORKERS = 2
WAIT_SECONDS = 20
UNUSED_DAYS = 60
DIR_NAME = "thumbnails"

_SLOTS = threading.BoundedSemaphore(WORKERS)


class ThumbnailError(UserError):
    """No hay miniatura de ese archivo (no se puede, es demasiado grande o falló): el explorador enseña el icono."""

    def __init__(self, message: str, busy: bool = False):
        super().__init__(message)
        self.busy = busy


@functools.cache
def _pillow():
    try:
        from PIL import Image, ImageOps, features  # noqa: PLC0415 (dependencia opcional)
    except ImportError:
        return None
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    return Image, ImageOps, features


def available() -> bool:
    """Si Pillow está instalado (sin él no hay miniaturas)."""
    return _pillow() is not None


def pillow_version() -> str:
    try:
        from PIL import __version__  # noqa: PLC0415
    except ImportError:
        return ""
    return __version__


@functools.cache
def formats() -> dict[str, str]:
    """Extensión → formato de Pillow con el que se decodifica (``media_types.json``, ``image.thumbnails``), solo
    los que este Pillow sabe leer."""
    data = json.loads(preview.MEDIA_FILE.read_text(encoding="utf-8"))
    wanted = (data.get("image") or {}).get("thumbnails") or {}
    found = {}
    for ext, fmt in wanted.items():
        if preview.media_kind(ext) != "image" or not re.fullmatch(r"[A-Z0-9]{2,10}", str(fmt)):
            raise ValueError(f"{preview.MEDIA_FILE.name}: image.thumbnails: {ext} → {fmt} is not allowed")
        found[ext] = fmt
    pillow = _pillow()
    if pillow is None:
        return {}
    image = pillow[0]
    image.init()
    return {ext: fmt for ext, fmt in found.items() if fmt in image.OPEN}


def enabled(options: dict) -> bool:
    """``preview.*``: el visor, las imágenes y las miniaturas encendidos, y Pillow instalado."""
    return bool(options.get("enabled") and options.get("images") and options.get("thumbnails")) and available()


def can_thumb(name: str, options: dict) -> bool:
    """Si ``name`` tiene miniatura con los ajustes ``preview.*`` de ahora."""
    return enabled(options) and preview.kind_of(name, options) == "image" and preview.extension(name) in formats()


def cache_dir(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / DIR_NAME


def _output() -> tuple[str, str, str]:
    """(formato de Pillow, extensión, MIME) de las miniaturas: WebP si este Pillow lo escribe; si no, PNG."""
    pillow = _pillow()
    if pillow is not None and pillow[2].check("webp"):
        return "WEBP", ".webp", "image/webp"
    return "PNG", ".png", "image/png"


def mimetype() -> str:
    return _output()[2]


def _key(root: dict, rel: str, entry) -> str:
    raw = f"{root.get('where')}\0{rel}\0{entry.size}\0{int(entry.mtime or 0)}"
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()


def path_for(cfg: dict, root: dict, rel: str, entry) -> Path:
    key = _key(root, rel, entry)
    return cache_dir(cfg["data_dir"]) / key[:2] / (key + _output()[1])


def get(cfg: dict, root: dict, rel: str, entry) -> Path:
    """La miniatura de ``rel`` (generada ahora si no estaba). :class:`ThumbnailError` si no puede haberla."""
    options = cfg["preview"]
    name = backends.name_of(rel)
    if entry is None or entry.is_dir or not can_thumb(name, options):
        raise ThumbnailError(_("This file has no thumbnail."))
    target = path_for(cfg, root, rel, entry)
    if target.is_file():
        _touch(target)
        return target
    limit = int(options.get("thumbnail_max_mb") or 0) * 1024 * 1024
    if limit and entry.size > limit:
        raise ThumbnailError(_("The image is too large for a thumbnail."))
    if not _SLOTS.acquire(timeout=WAIT_SECONDS):
        raise ThumbnailError(_("Too many thumbnails at once: try again in a moment."), busy=True)
    try:
        if target.is_file():                 # la hizo otra petición mientras esta esperaba
            return target
        data = _read(root, rel, limit)
        _render(data, formats()[preview.extension(name)], target)
    finally:
        _SLOTS.release()
    return target


def _read(root: dict, rel: str, limit: int) -> bytes:
    try:
        fh, _size, _mtime = root["backend"].open(rel)
    except (OSError, backends.BackendError) as exc:
        raise ThumbnailError(getattr(exc, "message", "") or _("The image cannot be read.")) from exc
    try:
        data = fh.read(limit + 1) if limit else fh.read()
    except (OSError, backends.BackendError) as exc:
        raise ThumbnailError(_("The image cannot be read.")) from exc
    finally:
        fh.close()
    if limit and len(data) > limit:
        raise ThumbnailError(_("The image is too large for a thumbnail."))
    return data


def _render(data: bytes, fmt: str, target: Path) -> None:
    image_mod, image_ops, _features = _pillow()
    out_fmt, _ext, _mime = _output()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", image_mod.DecompressionBombWarning)   # un aviso, aquí, es un error
            with image_mod.open(io.BytesIO(data), formats=[fmt]) as img:
                if img.width * img.height > MAX_PIXELS:
                    raise ThumbnailError(_("The image is too large for a thumbnail."))
                img.draft("RGB", (SIZE * 2, SIZE * 2))          # JPEG: decodifica ya reducida (mucho más rápido)
                img = image_ops.exif_transpose(img)                # las fotos del móvil, derechas
                img.thumbnail((SIZE, SIZE))
                alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
                img = img.convert("RGBA" if alpha else "RGB")
                buffer = io.BytesIO()
                img.save(buffer, out_fmt, **({"quality": 80, "method": 4} if out_fmt == "WEBP" else {"optimize": True}))
    except ThumbnailError:
        raise
    except Exception as exc:  # noqa: BLE001 (Pillow lanza de todo con un archivo roto o malicioso)
        log.info("No thumbnail: %s", exc)
        raise ThumbnailError(_("The image cannot be read.")) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, buffer.getvalue())


def _touch(path: Path) -> None:
    """Marca la miniatura como usada (la limpieza borra antes las que nadie pide)."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def cleanup(data_dir: str | os.PathLike, max_mb: int, unused_days: int = UNUSED_DAYS) -> int:
    """Borra las que nadie pide desde ``unused_days`` días y, si aun así ocupan más de ``max_mb``, las menos
    usadas hasta quedar en el 90 %. Devuelve cuántas borró."""
    base = cache_dir(data_dir)
    if not base.is_dir():
        return 0
    files = []
    for path in base.glob("*/*"):
        try:
            info = path.stat()
        except OSError:
            continue
        files.append((info.st_mtime, info.st_size, path))
    removed, old = 0, time.time() - unused_days * 86400
    kept = []
    for mtime, size, path in files:
        if mtime < old or path.name.endswith(".tmp"):
            path.unlink(missing_ok=True)
            removed += 1
        else:
            kept.append((mtime, size, path))
    total, cap = sum(s for _m, s, _p in kept), max_mb * 1024 * 1024
    if cap and total > cap:
        for _mtime, size, path in sorted(kept):
            if total <= cap * 0.9:
                break
            path.unlink(missing_ok=True)
            total -= size
            removed += 1
    return removed


def usage(data_dir: str | os.PathLike) -> dict:
    """Cuántas hay y cuánto ocupan (para *Sistema → Vista previa*)."""
    count, size = 0, 0
    base = cache_dir(data_dir)
    if base.is_dir():
        for path in base.glob("*/*"):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                continue
    return {"count": count, "bytes": size}


@maintenance.task("thumbnail_cleanup", every=lambda cfg: 24 if cfg["preview"].get("thumbnails") else 0, order=70)
def _cleanup_task(conn, cfg: dict) -> None:
    removed = cleanup(cfg["data_dir"], int(cfg["preview"].get("thumbnail_cache_mb") or 0))
    if removed:
        log.info("Thumbnails removed: %s", removed)

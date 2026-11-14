"""Subidas por partes (chunked) y reanudables.

Flujo:
    1. init:     se valida nombre, tamaño y espacio libre; se crea ``.sw-upload-<id>.part`` vacío
    2. append:   se añaden partes en orden; el offset debe coincidir con el tamaño actual del .part
                 (si no, 409 con el offset correcto para que el cliente continúe desde ahí)
    3. finalize: con el tamaño completo se guarda con el nombre final (sin sobrescribir)

El ``.part`` está en la zona local del backend (``Backend.staging_dir``): en el disco del servidor,
junto al destino (al terminar, renombrado atómico); con S3 o SMB, en ``<data_dir>/uploads`` (al
terminar se envía). El progreso real es su tamaño, así que una subida interrumpida (corte de red,
recarga de la página, reinicio del servidor) puede continuar donde se quedó.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from ..i18n import _
from .security import UPLOAD_TMP_PREFIX
from .backends import Backend, BackendError

MB = 1024 * 1024
MAX_CHUNK = 32 * MB          # tamaño de parte que usa el navegador
COPY_BLOCK = 1 * MB
STALE_HOURS = 24             # las subidas sin actividad se descartan pasado este tiempo
DISK_MARGIN = 64 * MB        # espacio libre mínimo que se deja en el disco


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra


def chunk_size(max_request_mb: int) -> int:
    """Parte más grande posible sin superar el límite por petición (con 1 MB de margen)."""
    return max(MB, min(MAX_CHUNK, max_request_mb * MB - MB))


def part_path(directory: Path, upload_id: str) -> Path:
    return directory / f"{UPLOAD_TMP_PREFIX}{upload_id}.part"


def validate_size(size, max_file_size_mb: int) -> int:
    try:
        size = int(size)
    except (TypeError, ValueError) as exc:
        raise UploadError(_("Invalid file size")) from exc
    if size < 0:
        raise UploadError(_("Invalid file size"))
    if max_file_size_mb and size > max_file_size_mb * MB:
        raise UploadError(_("The file exceeds the maximum allowed (%(max)s MB)", max=max_file_size_mb), 413)
    return size


def check_space(backend: Backend, dir_rel: str, size: int) -> None:
    """Espacio para el archivo: en el destino si es el disco del servidor; si no, en la zona local."""
    free = backend.free_space(dir_rel)
    if free is None:
        free = backend.staging_free()
    if free is not None and size + DISK_MARGIN > free:
        raise UploadError(_("Not enough space on the server for this file"), 507)


def received(part: Path) -> int:
    try:
        return part.stat().st_size
    except FileNotFoundError:
        raise UploadError(_("The upload no longer exists; start again"), 404) from None


def append(part: Path, stream: BinaryIO, offset: int, total: int) -> int:
    """Añade el contenido de ``stream`` al .part en ``offset``. Devuelve el nuevo tamaño."""
    current = received(part)
    if offset != current:
        raise UploadError(_("Wrong offset"), 409, received=current)
    written = 0
    with open(part, "ab") as fh:
        while True:
            block = stream.read(COPY_BLOCK)
            if not block:
                break
            written += len(block)
            if current + written > total:
                fh.truncate(current)
                raise UploadError(_("More data received than declared"), 400, received=current)
            fh.write(block)
    return current + written


def finalize(part: Path, backend: Backend, dir_rel: str, filename: str, total: int) -> str:
    """Guarda la subida completa como ``filename`` (o ``filename (1)``…) y devuelve su ruta relativa."""
    size = received(part)
    if size != total:
        raise UploadError(_("The upload is incomplete"), 409, received=size)
    try:
        final = backend.unique_rel(dir_rel, filename)
        backend.store(part, final)
    except BackendError as exc:
        raise UploadError(exc.message, 502) from exc
    return final


def discard(part: Path) -> None:
    try:
        part.unlink()
    except FileNotFoundError:
        pass

"""Subidas por partes (chunked) y reanudables.

Flujo:
    1. init:     se valida nombre, tamaño y espacio libre; se crea ``.sw-upload-<id>.part`` vacío
    2. append:   se añaden partes en orden; el offset debe coincidir con el tamaño actual del .part
                 (si no, 409 con el offset correcto para que el cliente continúe desde ahí)
    3. finalize: con el tamaño completo se renombra atómicamente al nombre final (sin sobrescribir)

El progreso real es el tamaño del ``.part`` en disco, así que una subida interrumpida (corte de red,
recarga de la página, reinicio del servidor) puede continuar donde se quedó.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import BinaryIO

from .security import UPLOAD_TMP_PREFIX
from .storage import unique_path

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
        raise UploadError("Tamaño de archivo no válido") from exc
    if size < 0:
        raise UploadError("Tamaño de archivo no válido")
    if max_file_size_mb and size > max_file_size_mb * MB:
        raise UploadError(f"El archivo supera el máximo permitido ({max_file_size_mb} MB)", 413)
    return size


def check_space(directory: Path, size: int) -> None:
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        return
    if size + DISK_MARGIN > free:
        raise UploadError("No hay espacio suficiente en el servidor para este archivo", 507)


def received(part: Path) -> int:
    try:
        return part.stat().st_size
    except FileNotFoundError:
        raise UploadError("La subida ya no existe; vuelve a empezar", 404) from None


def append(part: Path, stream: BinaryIO, offset: int, total: int) -> int:
    """Añade el contenido de ``stream`` al .part en ``offset``. Devuelve el nuevo tamaño."""
    current = received(part)
    if offset != current:
        raise UploadError("Offset incorrecto", 409, received=current)
    written = 0
    with open(part, "ab") as fh:
        while True:
            block = stream.read(COPY_BLOCK)
            if not block:
                break
            written += len(block)
            if current + written > total:
                fh.truncate(current)
                raise UploadError("Se han recibido más datos de los declarados", 400, received=current)
            fh.write(block)
    return current + written


def finalize(part: Path, directory: Path, filename: str, total: int) -> Path:
    size = received(part)
    if size != total:
        raise UploadError("La subida está incompleta", 409, received=size)
    final = unique_path(directory, filename)
    os.replace(part, final)
    return final


def discard(part: Path) -> None:
    try:
        part.unlink()
    except FileNotFoundError:
        pass

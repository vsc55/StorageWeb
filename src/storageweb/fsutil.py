"""Escribir ficheros de StorageWeb (claves, listas, imágenes, miniaturas) sin dejar nunca uno a medias ni con permisos de
más. Sin dependencias."""
from __future__ import annotations

import os
import threading
from pathlib import Path


def atomic_write(path: Path, data: bytes | str) -> None:
    """Escribe ``path`` entero de una vez: en un temporal de la misma carpeta (único por proceso e hilo) y luego
    ``os.replace``, así quien lo lea a la vez ve el anterior o el nuevo, nunca medio."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    if isinstance(data, str):
        tmp.write_text(data, encoding="utf-8")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def write_private(path: Path, text: str, *, exclusive: bool = True) -> None:
    """Un fichero que solo puede leer el usuario del servicio (0600): una clave. ``exclusive``: solo si no existe
    (``FileExistsError`` si otro proceso lo acaba de crear); si no, lo sustituye de una vez."""
    path = Path(path)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        return
    tmp = path.with_name(f".{path.name}.nuevo")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)

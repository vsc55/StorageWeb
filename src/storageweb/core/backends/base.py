"""Interfaz común de los almacenamientos y rutas relativas seguras.

Cada carpeta (personal o compartida) tiene un backend atado a su raíz. Todas las operaciones reciben
rutas **relativas a esa raíz**, en formato POSIX (``"informes/2026/enero.pdf"``; ``""`` es la raíz),
que pasan siempre por :func:`clean_rel`: nada de ``..``, rutas absolutas ni barras invertidas.
"""
from __future__ import annotations

import io
import posixpath
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from ...i18n import _
from ...settings.location_types import LocationSchema
from ..security import PathError


@dataclass
class Entry:
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0  # marca de tiempo Unix


class BackendError(Exception):
    """Fallo del almacenamiento (conexión, credenciales, permisos…), con un mensaje para el usuario."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def certificate_error(exc: Exception) -> BackendError:
    """Certificado TLS que no se puede verificar (autofirmado, de otro nombre…), con la salida."""
    return BackendError(_("The certificate of the server could not be verified (%(error)s). If the server uses its "
                          "own certificate, disable «Check the certificate».",
                          error=getattr(exc, "verify_message", "") or exc))


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")


def clean_rel(sub: str) -> str:
    """Ruta relativa normalizada (``a/b``), o :class:`PathError` si no es segura.

    Rechaza ``..`` (salir de la raíz), unidades de Windows (``C:…``) y caracteres de control (NUL, CR,
    LF…: en FTP serían comandos nuevos y en HTTP, cabeceras). Las barras invertidas cuentan como
    separadores y las barras iniciales se quitan: siempre queda una ruta relativa a la raíz.
    """
    text = str(sub or "")
    if _CONTROL.search(text):
        raise PathError(sub)
    parts = [p for p in text.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or (parts and _DRIVE.match(parts[0])):
        raise PathError(sub)
    return "/".join(parts)


def is_safe_name(name: str) -> bool:
    """Un único nombre (sin separadores, ``.``/``..`` ni caracteres de control): lo que puede devolver un listado."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name \
        and not _CONTROL.search(name)


def join_rel(*parts: str) -> str:
    return clean_rel("/".join(p for p in parts if p))


def parent_rel(rel: str) -> str:
    return posixpath.dirname(clean_rel(rel))


def name_of(rel: str) -> str:
    return PurePosixPath(rel).name


class IterStream(io.RawIOBase):
    """Un iterable de bloques de bytes (descarga por trozos) visto como fichero que se lee."""

    def __init__(self, chunks: Iterable[bytes]):
        super().__init__()
        self._chunks = iter(chunks)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        n = min(len(buffer), len(self._buffer))
        buffer[:n] = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return n


class RangedReader(io.RawIOBase):
    """Fichero remoto con ``seek``: al leer, pide al servidor desde la posición actual (``Range``, ``REST``…).

    ``fetch(pos)`` abre la lectura desde ``pos`` y devuelve algo con ``read(n)`` (y ``close()`` si hace
    falta). Si se salta a otra posición se cierra y se vuelve a pedir: así funcionan las descargas
    reanudadas y el vídeo sin bajar el archivo entero.
    """

    def __init__(self, fetch: Callable[[int], object], size: int):
        super().__init__()
        self.fetch, self.size = fetch, size
        self.pos = 0
        self.body = None

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        new = {io.SEEK_SET: offset, io.SEEK_CUR: self.pos + offset, io.SEEK_END: self.size + offset}[whence]
        if new != self.pos:
            self._drop()
        self.pos = max(0, new)
        return self.pos

    def readinto(self, buffer) -> int:
        if self.pos >= self.size:
            return 0
        if self.body is None:
            self.body = self.fetch(self.pos)
        data = self.body.read(len(buffer))
        buffer[:len(data)] = data
        self.pos += len(data)
        return len(data)

    def _drop(self) -> None:
        if self.body is not None:
            try:
                close = getattr(self.body, "close", None)
                if close:
                    close()
            except Exception:  # noqa: BLE001 (cerrar una lectura a medias puede fallar; da igual)
                pass
            self.body = None

    def close(self) -> None:
        self._drop()
        super().close()


class Backend:
    """Almacenamiento de una raíz. Las subclases implementan las operaciones básicas."""

    kind = ""

    def __init__(self, staging: Path):
        self.staging = staging  # zona local para recibir las subidas por partes

    # ------------------------------------------------------------------ a implementar
    def describe(self) -> str:
        raise NotImplementedError

    def stat(self, rel: str) -> Entry | None:
        """La entrada, o ``None`` si no existe."""
        raise NotImplementedError

    def listdir(self, rel: str) -> list[Entry]:
        raise NotImplementedError

    def open(self, rel: str) -> tuple[BinaryIO, int, float]:
        """Fichero para leer (con ``seek``), su tamaño y su fecha de modificación."""
        raise NotImplementedError

    def mkdir(self, rel: str) -> None:
        """Crea una carpeta. :class:`FileExistsError` si ya existe algo con ese nombre."""
        raise NotImplementedError

    def rename(self, rel: str, new_name: str) -> str:
        """Renombra dentro de la misma carpeta y devuelve la ruta nueva."""
        raise NotImplementedError

    def delete(self, rel: str) -> None:
        """Borra un archivo o una carpeta con todo su contenido."""
        raise NotImplementedError

    def store(self, local: Path, rel: str) -> None:
        """Guarda en ``rel`` un archivo local ya completo (y lo quita de la zona local)."""
        raise NotImplementedError

    def root_exists(self) -> bool:
        raise NotImplementedError

    def ensure_root(self, home: bool = False) -> None:
        """Crea la raíz si no existe (``create_home`` / ``create_shares``)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ comunes
    def check(self) -> None:
        """Comprueba la conexión y el acceso a la raíz; :class:`BackendError` si falla."""
        if not self.root_exists():
            raise BackendError(_("The folder does not exist on the server: %(where)s", where=self.describe()))
        self.listdir("")

    def local_path(self, rel: str) -> Path | None:
        """Ruta en disco si el almacenamiento es local (descargas con ``send_file``); si no, ``None``."""
        return None

    def is_dir(self, rel: str) -> bool:
        entry = self.stat(rel)
        return bool(entry and entry.is_dir)

    def is_file(self, rel: str) -> bool:
        entry = self.stat(rel)
        return bool(entry and not entry.is_dir)

    def exists(self, rel: str) -> bool:
        return self.stat(rel) is not None

    def unique_rel(self, dir_rel: str, name: str) -> str:
        """Ruta libre para ``name`` en la carpeta: ``informe (1).pdf`` si ya existe ``informe.pdf``."""
        candidate = join_rel(dir_rel, name)
        if not self.exists(candidate):
            return candidate
        stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
        for i in range(1, 10000):
            candidate = join_rel(dir_rel, f"{stem} ({i}){suffix}")
            if not self.exists(candidate):
                return candidate
        raise FileExistsError(name)

    def staging_dir(self, dir_rel: str) -> Path:
        """Carpeta local donde se reciben las subidas por partes con destino ``dir_rel``."""
        self.staging.mkdir(parents=True, exist_ok=True)
        return self.staging

    def free_space(self, dir_rel: str) -> int | None:
        """Espacio libre en el destino, si se sabe (en los remotos solo cuenta la zona local)."""
        return None

    def staging_free(self) -> int | None:
        try:
            return shutil.disk_usage(self.staging_dir("")).free
        except OSError:
            return None


class UnavailableBackend(Backend):
    """Raíz cuyo almacenamiento no se puede usar (falta la biblioteca, ubicación borrada…).

    Cualquier operación lanza :class:`BackendError` con el motivo, así que el resto de carpetas siguen
    funcionando y esta muestra el error al abrirla.
    """

    kind = "unavailable"

    def __init__(self, message: str, staging: Path):
        super().__init__(staging)
        self.message = message

    def describe(self) -> str:
        return self.message

    def _fail(self, *_args, **_kwargs):
        raise BackendError(self.message)

    stat = listdir = open = mkdir = rename = delete = store = ensure_root = check = _fail

    def root_exists(self) -> bool:
        return False


class RemoteBackend(Backend):
    """Backend de un tipo de ubicación externa (S3, SMB…).

    Cada subclase declara su :attr:`schema` (opciones, etiquetas, documentación) e implementa
    :meth:`connect`, :meth:`create` y :meth:`address`. ``core.backends.discover()`` la encuentra sola
    en ``core/backends/``: un tipo nuevo no toca código general.
    """

    schema: LocationSchema | None = None

    @classmethod
    def connect(cls, location: dict):
        """Cliente de la biblioteca para la ubicación (se crea una vez por proceso y ubicación)."""
        raise NotImplementedError

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> RemoteBackend:
        """Backend de una raíz: ``base`` es la ruta de la carpeta dentro de la ubicación."""
        raise NotImplementedError

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        """Dirección legible de ``path`` dentro de la ubicación (``s3://…``, ``\\servidor\…``)."""
        raise NotImplementedError

    @classmethod
    def missing_library(cls, library: str) -> BackendError:
        return BackendError(_("%(type)s needs the %(library)s library: pip install 'storageweb[%(extra)s]'.",
                              type=cls.schema.short_label, library=library, extra=cls.schema.extra))

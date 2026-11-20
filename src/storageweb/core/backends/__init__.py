"""Dónde viven los archivos de cada carpeta: disco local o una ubicación externa (S3, SMB…).

Una **ubicación** (``storage.locations``) es una conexión con nombre a un almacenamiento externo; las
carpetas compartidas y las personales eligen una (``location``; vacía = disco local) y una ruta dentro
de ella. :func:`backend_for` devuelve el :class:`Backend` de una raíz.

**Tipos de ubicación.** Cada módulo de este paquete puede definir una subclase de
:class:`RemoteBackend` con su ``schema``; :func:`discover` los encuentra y los registra (también el
esquema en ``settings.location_types``, que usan el cargador, la web y la documentación). Para añadir
un tipo basta con un fichero nuevo aquí.

Los clientes de cada biblioteca se crean una vez por proceso y ubicación. Los tests sustituyen
:data:`CLIENT_FACTORIES` por clientes en memoria.
"""
from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import threading
from pathlib import Path

from ...i18n import _
from ...settings import location_types
from .base import (Backend, BackendError, Entry, RemoteBackend, UnavailableBackend, clean_rel, copy_between,
                   is_safe_name, join_rel, name_of, parent_rel)
from .local import LocalBackend

TYPES: dict[str, type[RemoteBackend]] = {}
CLIENT_FACTORIES: dict[str, object] = {}  # tipo → función que crea el cliente (los tests la sustituyen)
_clients: dict[str, object] = {}
_lock = threading.Lock()


def discover() -> dict[str, type[RemoteBackend]]:
    """Importa los módulos del paquete y registra cada subclase de RemoteBackend con ``schema``."""
    for info in pkgutil.iter_modules(__path__):
        if info.name in ("base", "local"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, RemoteBackend) and cls.schema is not None and cls.__module__ == module.__name__:
                register(cls)
    return TYPES


def register(cls: type[RemoteBackend]) -> None:
    """Registra un tipo de ubicación (lo hace :func:`discover`; también sirve para plugins externos)."""
    kind = cls.schema.kind
    if kind in TYPES and TYPES[kind] is not cls:
        raise RuntimeError(f"Storage type {kind!r} defined twice: {TYPES[kind]} and {cls}")
    TYPES[kind] = cls
    CLIENT_FACTORIES.setdefault(kind, cls.connect)
    location_types.register(cls.schema)


def _client(location: dict):
    key = json.dumps(location, sort_keys=True)  # si cambian las credenciales, cliente nuevo
    with _lock:
        if key not in _clients:
            _clients[key] = CLIENT_FACTORIES[location["type"]](location)
        return _clients[key]


def clear_clients() -> None:
    with _lock:
        _clients.clear()


def find_location(cfg: dict, name: str) -> dict | None:
    return next((loc for loc in cfg["storage"].get("locations", []) if loc["name"] == name), None)


def type_of(location: dict) -> type[RemoteBackend]:
    try:
        return TYPES[location["type"]]
    except KeyError:
        raise BackendError(_("Unknown storage type: %(type)s", type=location["type"])) from None


def address(location: dict, path: str = "") -> str:
    """Dirección legible de ``path`` dentro de la ubicación (``s3://…``, ``\\\\servidor\\…``)."""
    return type_of(location).address(location, path)


def backend_for(location: dict | None, base: str, staging: Path) -> Backend:
    """Backend de una raíz: ``base`` es la ruta local (sin ubicación) o la ruta dentro de la ubicación."""
    if not location:
        return LocalBackend(Path(base), staging)
    try:
        cls = type_of(location)
        backend = cls.create(_client(location), location, base, staging)
        backend.windows_names = bool(location.get("windows_server"))
        return backend
    except BackendError as exc:
        return UnavailableBackend(exc.message, staging)
    except Exception as exc:  # noqa: BLE001 (p. ej. no se puede abrir la sesión SMB)
        return UnavailableBackend(_("Cannot connect to the storage location %(name)s: %(error)s",
                                    name=location["name"], error=exc), staging)


def staging_dir(cfg: dict) -> Path:
    """Zona local donde se reciben las subidas con destino S3 o SMB antes de enviarlas."""
    return Path(cfg["data_dir"]) / "uploads"


discover()

__all__ = ["CLIENT_FACTORIES", "TYPES", "Backend", "BackendError", "Entry", "LocalBackend", "RemoteBackend",
           "UnavailableBackend", "address", "backend_for", "clean_rel", "clear_clients", "copy_between", "discover",
           "find_location",
           "is_safe_name", "join_rel", "name_of", "parent_rel", "register", "staging_dir", "type_of"]

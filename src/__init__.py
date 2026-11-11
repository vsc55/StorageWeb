"""StorageWeb: servidor web para subir y descargar archivos."""
from __future__ import annotations

__version__ = "1.0.0"


def create_app(config_path: str | None = None):
    from .app import create_app as _create_app

    return _create_app(config_path)

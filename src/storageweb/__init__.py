"""StorageWeb: servidor web para subir y descargar archivos."""
from __future__ import annotations

__version__ = "0.2.0"

# Punto de ensamblado: registra lo que se descubre solo antes de que nada lea la configuración (los
# valores por defecto y la validación de auth.* y storage.locations dependen de ello):
# - providers: métodos de inicio de sesión (providers/<método>/)
# - core: tipos de ubicación de almacenamiento (core/backends/<tipo>.py)
from . import core, providers  # noqa: E402,F401


def create_app(config_path: str | None = None):
    from .app import create_app as _create_app

    return _create_app(config_path)

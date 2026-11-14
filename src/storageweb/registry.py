"""Descubrimiento de extensiones: importar los módulos de un paquete para que se registren solos.

Los registros de StorageWeb (avisos del Resumen, tareas de mantenimiento, tipos de almacenamiento,
métodos de inicio de sesión, comandos de la CLI, resultados del buscador) se rellenan con decoradores
en el módulo que sabe de cada cosa. :func:`import_submodules` garantiza que esos módulos estén
importados antes de recorrer el registro, sin una lista a mano de quién aporta qué.
"""
from __future__ import annotations

import importlib
import pkgutil
import threading

_done: set[str] = set()
_lock = threading.RLock()


def import_submodules(package: str) -> None:
    """Importa (una vez) todos los módulos y subpaquetes de ``package``."""
    with _lock:
        if package in _done:
            return
        _done.add(package)  # antes de importar: un módulo puede volver a llamar aquí
        pkg = importlib.import_module(package)
        for info in pkgutil.walk_packages(pkg.__path__, f"{package}."):
            importlib.import_module(info.name)

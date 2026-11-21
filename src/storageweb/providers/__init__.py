"""Proveedores de identidad: un método de inicio de sesión por carpeta, que se descubre solo.

* ``local/`` — contraseñas de usuarios locales (SQLite)
* ``pam/``   — usuarios del sistema operativo
* ``entra/`` — Microsoft Entra ID: SSO (``oauth2`` propio, por defecto, y ``msal``), comprobación,
  directorio de grupos y registro de la aplicación

Cada carpeta define una subclase de :class:`AuthMethod` (``base.py``) con su configuración.
:func:`discover` importa el paquete y registra cada una (también su configuración en
``settings.auth_methods``). Añadir un método es añadir su carpeta: ver *Desarrollo → Extender*.
"""
from __future__ import annotations

from .. import registry
from ..settings import auth_methods
from .base import (AuthDenied, AuthMethod, DirectoryPerson, DirectoryUser, GroupDirectory, Identity, LoginButton, Notice,
                   SSOError, SSOProvider)

_METHODS: dict[str, AuthMethod] = {}


def register(cls: type[AuthMethod]) -> AuthMethod:
    current = _METHODS.get(cls.key)
    if current is not None:
        if type(current) is not cls:
            raise RuntimeError(f"Sign-in method {cls.key!r} defined twice: {type(current)} and {cls}")
        return current
    method = cls()
    _METHODS[cls.key] = method
    auth_methods.register(cls.config)
    return method


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def discover() -> list[AuthMethod]:
    """Importa los proveedores y registra cada método (subclase de AuthMethod con ``key`` y ``config``)."""
    registry.import_submodules(__name__)
    for cls in _subclasses(AuthMethod):  # solo las de este paquete (las de fuera, con register())
        if cls.key and cls.config is not None and cls.__module__.startswith(f"{__name__}."):
            register(cls)
    return methods()


def methods() -> list[AuthMethod]:
    return sorted(_METHODS.values(), key=lambda m: (m.order, m.key))


def get(key: str) -> AuthMethod | None:
    return _METHODS.get(key)


discover()

__all__ = ["AuthDenied", "AuthMethod", "DirectoryPerson", "DirectoryUser", "GroupDirectory", "Identity", "LoginButton", "Notice", "SSOError",
           "SSOProvider", "discover", "get", "methods", "register"]

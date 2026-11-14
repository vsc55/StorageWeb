"""Configuración de los métodos de inicio de sesión (``auth.<método>``): la declara cada proveedor.

Cada método (``providers/<método>/``) registra aquí su :class:`AuthConfig`: valores por defecto,
descripción de cada campo (referencia generada, etiquetas de la web, buscador), secretos, diccionarios
que cuentan como un solo valor y su validación. :func:`register` lo incorpora a ``DEFAULTS["auth"]``,
a ``fields.FIELDS`` y a las listas de secretos; el cargador valida ``auth`` llamando a cada uno.

Así ``settings`` no sabe qué métodos hay ni depende de ``providers`` (capas: settings es la base).
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass

from . import defaults
from .fields import FIELDS, Field


@dataclass(frozen=True)
class AuthConfig:
    key: str                                   # auth.<key>; también users.source
    defaults: dict                             # valores por defecto (siempre con "enabled")
    fields: dict[str, Field]                   # ruta relativa ("tenant_id") → descripción
    validate: Callable[[dict, dict], None] = lambda section, cfg: None  # normaliza en el sitio o ConfigError
    secrets: tuple[str, ...] = ()              # rutas relativas que nunca se muestran
    leaf: tuple[str, ...] = ()                 # diccionarios que se guardan enteros (role_mappings)
    order: int = 50

    def __post_init__(self):
        if "enabled" not in self.defaults:
            raise ValueError(f"auth.{self.key}: the defaults need 'enabled'")


_CONFIGS: dict[str, AuthConfig] = {}


def register(config: AuthConfig) -> None:
    current = _CONFIGS.get(config.key)
    if current is config:
        return
    if current is not None:
        raise ValueError(f"Sign-in method {config.key!r} registered twice")
    _CONFIGS[config.key] = config
    ordered = sorted(_CONFIGS.values(), key=lambda c: (c.order, c.key))
    auth = defaults.DEFAULTS.setdefault("auth", {})
    rebuilt = {c.key: auth.get(c.key, copy.deepcopy(c.defaults)) for c in ordered}
    auth.clear()
    auth.update(rebuilt)
    for rel, info in config.fields.items():
        FIELDS[f"auth.{config.key}.{rel}"] = info
    for rel in config.secrets:
        defaults.SECRET_FIELDS.append(("auth", config.key, *rel.split(".")))
        defaults.SECRET_PATHS.add(f"auth.{config.key}.{rel}")
    for rel in config.leaf:
        defaults.LEAF_PATHS.append(("auth", config.key, *rel.split(".")))


def configs() -> list[AuthConfig]:
    return sorted(_CONFIGS.values(), key=lambda c: (c.order, c.key))


def get(key: str) -> AuthConfig | None:
    return _CONFIGS.get(key)

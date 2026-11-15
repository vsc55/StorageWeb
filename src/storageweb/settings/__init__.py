"""Configuración por capas: predeterminados < ajustes web (SQLite) < config.json < variables de entorno.

* ``defaults`` — valores predeterminados y constantes
* ``fields``   — registro de los campos: documentación, etiqueta, página y sinónimos de cada uno
* ``layers``   — combinar capas campo a campo y recorrer campos por ruta
* ``env``      — variables de entorno ``STORAGEWEB_*``
* ``loader``   — leer config.json y validar
* ``runtime``  — ajustes guardados desde la web, bloqueos y orígenes de cada valor
"""
from . import fields  # noqa: F401
from .defaults import DEFAULTS, PERMISSIONS, ROLES, RUNTIME_SECTIONS, SECRET_PATHS, is_secret
from .env import ENV_ALIASES, env_config, env_name, setting_paths
from .errors import ConfigError
from .layers import (deep_merge, diff_overrides, drop_path, get_path, leaf_paths, merge_overrides, runtime_part,
                     runtime_view)
from .loader import default_config_path, ensure_secret_key, load_config, mask_secrets, normalize, read_config_file
from .runtime import ORIGINS, RuntimeSettings
from . import store

__all__ = [
    "DEFAULTS", "ENV_ALIASES", "is_secret", "ORIGINS", "PERMISSIONS", "ROLES", "RUNTIME_SECTIONS", "SECRET_PATHS",
    "ConfigError", "RuntimeSettings", "deep_merge", "default_config_path", "diff_overrides", "drop_path",
    "ensure_secret_key", "env_config", "env_name", "fields", "get_path", "leaf_paths", "load_config", "mask_secrets",
    "merge_overrides", "normalize", "read_config_file", "runtime_part", "runtime_view", "setting_paths",
]

"""Configuración: valores por defecto, carga de config.json y ajustes editables desde la web."""
from .defaults import DEFAULTS, PERMISSIONS, ROLES, RUNTIME_SECTIONS
from .loader import (PROJECT_ROOT, ConfigError, default_config_path, ensure_secret_key, load_config,
                     mask_secrets, normalize, read_config_file, runtime_view)

__all__ = [
    "DEFAULTS", "PERMISSIONS", "ROLES", "RUNTIME_SECTIONS", "PROJECT_ROOT", "ConfigError",
    "default_config_path", "ensure_secret_key", "load_config", "mask_secrets", "normalize",
    "read_config_file", "runtime_view",
]

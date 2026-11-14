"""Configuración: valores por defecto, carga y validación de config.json y ajustes web."""
from .defaults import DEFAULTS, PERMISSIONS, ROLES, RUNTIME_SECTIONS
from .loader import (ConfigError, deep_merge, default_config_path, diff_overrides, drop_path, ensure_secret_key,
                     leaf_paths, load_config, mask_secrets, merge_overrides, normalize, read_config_file,
                     runtime_view)
from .runtime import RUNTIME_KEY, RuntimeSettings

__all__ = [
    "DEFAULTS", "PERMISSIONS", "ROLES", "RUNTIME_SECTIONS", "RUNTIME_KEY", "ConfigError",
    "RuntimeSettings", "deep_merge", "default_config_path", "ensure_secret_key", "load_config",
    "mask_secrets", "normalize", "read_config_file", "runtime_view", "diff_overrides", "drop_path",
    "leaf_paths", "merge_overrides",
]

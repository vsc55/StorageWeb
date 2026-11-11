"""Ajustes efectivos durante una petición: config.json + ajustes guardados desde la web.

Los ajustes web se guardan en la tabla ``settings`` con un número de revisión; cada proceso
cachea la configuración combinada y solo la recalcula cuando cambia la revisión.
"""
from __future__ import annotations

import copy
import threading

from flask import current_app, g

from ..db import settings as settings_repo
from .defaults import SECRET_FIELDS
from .loader import ConfigError, _get, _set, normalize

RUNTIME_KEY = "runtime"
_lock = threading.Lock()


def _boot() -> dict:
    return current_app.extensions["sw_boot"]


def current() -> dict:
    """Configuración efectiva (cacheada por petición y por revisión)."""
    cached = g.get("sw_settings")
    if cached is not None:
        return cached
    boot = _boot()
    rev = settings_repo.revision(RUNTIME_KEY)
    with _lock:
        if boot["rev"] != rev:
            overrides = settings_repo.get(RUNTIME_KEY) or {}
            try:
                boot["cfg"] = normalize(boot["file"], boot["path"], overrides)
            except ConfigError:
                current_app.logger.exception("Ajustes web no válidos; se usa solo config.json")
                boot["cfg"] = normalize(boot["file"], boot["path"])
            boot["rev"] = rev
        cfg = boot["cfg"]
    g.sw_settings = cfg
    return cfg


def overrides() -> dict:
    return settings_repo.get(RUNTIME_KEY) or {}


def save(runtime: dict, username: str | None) -> dict:
    """Valida y guarda los ajustes editables. Lanza ConfigError si no son válidos."""
    runtime = copy.deepcopy(runtime)
    previous = overrides()
    for path in SECRET_FIELDS:
        if path[0] in runtime and not _get(runtime, path) and _get(previous, path):
            _set(runtime, path, _get(previous, path))  # vacío = conservar
    boot = _boot()
    normalize(boot["file"], boot["path"], runtime)  # valida
    settings_repo.put(RUNTIME_KEY, runtime, username)
    g.pop("sw_settings", None)
    return runtime


def reset(username: str | None) -> None:
    settings_repo.put(RUNTIME_KEY, {}, username)
    g.pop("sw_settings", None)

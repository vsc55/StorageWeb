"""Ajustes efectivos: config.json + ajustes guardados desde la web.

Los ajustes web se guardan en la tabla ``settings`` con un número de revisión. ``RuntimeSettings``
cachea la configuración combinada y solo la recalcula cuando cambia la revisión. No depende de
Flask: recibe la conexión a la base de datos en cada llamada.
"""
from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path
from sqlite3 import Connection

from ..db.repositories import settings as repo
from .defaults import SECRET_FIELDS
from .loader import ConfigError, _get, _set, normalize

RUNTIME_KEY = "runtime"
_log = logging.getLogger(__name__)


class RuntimeSettings:
    def __init__(self, file_cfg: dict, cfg_path: Path):
        self.file_cfg = file_cfg
        self.cfg_path = cfg_path
        self._lock = threading.Lock()
        self._rev: int | None = None
        self._cfg: dict | None = None

    def current(self, conn: Connection) -> dict:
        rev = repo.revision(conn, RUNTIME_KEY)
        with self._lock:
            if self._rev != rev:
                overrides = repo.get(conn, RUNTIME_KEY) or {}
                try:
                    self._cfg = normalize(self.file_cfg, self.cfg_path, overrides)
                except ConfigError:
                    _log.exception("Ajustes web no válidos; se usa solo config.json")
                    self._cfg = normalize(self.file_cfg, self.cfg_path)
                self._rev = rev
            return self._cfg

    def overrides(self, conn: Connection) -> dict:
        return repo.get(conn, RUNTIME_KEY) or {}

    def info(self, conn: Connection):
        return repo.info(conn, RUNTIME_KEY)

    def validate(self, runtime: dict) -> dict:
        return normalize(self.file_cfg, self.cfg_path, runtime)

    def save(self, conn: Connection, runtime: dict, username: str | None) -> dict:
        """Valida y guarda los ajustes editables. Lanza ConfigError si no son válidos."""
        runtime = copy.deepcopy(runtime)
        previous = self.overrides(conn)
        for path in SECRET_FIELDS:
            if path[0] in runtime and not _get(runtime, path) and _get(previous, path):
                _set(runtime, path, _get(previous, path))  # vacío = conservar el anterior
        self.validate(runtime)
        repo.put(conn, RUNTIME_KEY, runtime, username)
        return runtime

    def reset(self, conn: Connection, username: str | None) -> None:
        repo.put(conn, RUNTIME_KEY, {}, username)

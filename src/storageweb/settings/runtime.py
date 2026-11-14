"""Ajustes efectivos por capas: predeterminados < web (SQLite) < config.json < entorno.

Los ajustes web se guardan en la tabla ``settings`` con un número de revisión, como la diferencia
mínima con los valores predeterminados. ``RuntimeSettings`` cachea la configuración combinada y solo
la recalcula cuando cambia la revisión. No depende de Flask: recibe la conexión en cada llamada.

Un campo presente en config.json o en una variable de entorno está **bloqueado** (:meth:`locked`):
la web no lo puede cambiar ni restablecer, y lo que hubiera guardado para él no se usa.
"""
from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path
from sqlite3 import Connection

from ..db.repositories import settings as repo
from ..i18n import _
from .defaults import SECRET_FIELDS
from .env import env_name
from .errors import ConfigError
from .layers import _get, _set, diff_overrides, drop_path, leaf_paths, runtime_part, runtime_view
from .loader import normalize

RUNTIME_KEY = "runtime"


def runtime_key(profile: str = "default") -> str:
    """Clave de la tabla ``settings`` del perfil: ``runtime`` (el predeterminado) o ``runtime:<perfil>``."""
    return RUNTIME_KEY if profile == "default" else f"{RUNTIME_KEY}:{profile}"

ORIGINS = ("web", "file", "env")  # de dónde viene un valor que no es el predeterminado
_log = logging.getLogger(__name__)


class RuntimeSettings:
    def __init__(self, file_cfg: dict, cfg_path: Path, env_cfg: dict | None = None, profile: str = "default"):
        self.file_cfg = file_cfg
        self.cfg_path = cfg_path
        self.env_cfg = env_cfg or {}
        self.profile = profile
        self.key = runtime_key(profile)
        self.labeler = lambda path: path  # la web lo sustituye por la etiqueta visible del campo
        self._lock = threading.Lock()
        self._rev: int | None = None
        self._cfg: dict | None = None
        self._defaults: dict | None = None
        self._locked: dict[str, str] | None = None

    def _normalize(self, overrides: dict | None = None) -> dict:
        return normalize(self.file_cfg, self.cfg_path, overrides, self.env_cfg)

    # ------------------------------------------------------------------ capas

    def defaults(self) -> dict:
        """Secciones editables con sus valores predeterminados (rutas ya resueltas)."""
        if self._defaults is None:
            self._defaults = runtime_view(normalize({}, self.cfg_path))
        return self._defaults

    def locked(self) -> dict[str, str]:
        """Campos fijados fuera de la web: ``{ruta: "file" | "env"}`` (el entorno gana)."""
        if self._locked is None:
            found = {p: "file" for p in leaf_paths(runtime_part(self.file_cfg))}
            found.update({p: "env" for p in leaf_paths(runtime_part(self.env_cfg))})
            self._locked = found
        return self._locked

    def lock_of(self, dotted: str) -> str | None:
        """``"file"``/``"env"`` si el campo (o la lista o el diccionario que lo contiene) está bloqueado."""
        for path, source in self.locked().items():
            if dotted == path or dotted.startswith(path + ".") or path.startswith(dotted + "."):
                return source
        return None

    def lock_message(self, dotted: str) -> str:
        name = self.labeler(dotted)
        if self.lock_of(dotted) == "env":
            return _("«%(path)s» is set by the environment variable %(name)s and cannot be changed from the web.",
                     path=name, name=env_name(dotted))
        return _("«%(path)s» is set in config.json and cannot be changed from the web.", path=name)

    def lock_notice(self, dotted: str) -> str:
        """El mensaje de bloqueo si el campo está bloqueado; vacío si se puede cambiar."""
        return self.lock_message(dotted) if self.lock_of(dotted) else ""

    def modified_paths(self, conn: Connection) -> set[str]:
        """Campos cuyo valor efectivo no es el predeterminado."""
        return leaf_paths(diff_overrides(self.defaults(), runtime_view(self.current(conn))))

    def origins(self, conn: Connection) -> dict[str, str]:
        """Origen de cada campo que no sale de los predeterminados: ``web``, ``file`` o ``env``.

        Los bloqueados aparecen siempre, aunque su valor coincida con el predeterminado.
        """
        result = {p: "web" for p in self.modified_paths(conn)}
        for path in list(result):
            source = self.lock_of(path)
            if source:
                result[path] = source
        result.update(self.locked())
        return result

    # ------------------------------------------------------------------ lectura

    def current(self, conn: Connection) -> dict:
        rev = repo.revision(conn, self.key)
        with self._lock:
            if self._rev != rev:
                overrides = repo.get(conn, self.key) or {}
                try:
                    self._cfg = self._normalize(overrides)
                except ConfigError:
                    _log.exception("Ajustes web no válidos; se usan solo config.json y el entorno")
                    self._cfg = self._normalize()
                self._rev = rev
            return self._cfg

    def overrides(self, conn: Connection) -> dict:
        return repo.get(conn, self.key) or {}

    def info(self, conn: Connection):
        return repo.info(conn, self.key)

    def validate(self, runtime: dict) -> dict:
        return self._normalize(runtime)

    # ------------------------------------------------------------------ escritura

    def save(self, conn: Connection, runtime: dict, username: str | None, strict: bool = False) -> dict:
        """Valida y guarda los ajustes editables. Lanza ConfigError si no son válidos.

        Los campos bloqueados no se guardan. Con ``strict`` (cambios que no vienen de un formulario
        completo: matriz, carpetas, logo, Entra ID…) intentar cambiar uno es un error.
        """
        runtime = copy.deepcopy(runtime)
        previous = self.overrides(conn)
        for path in SECRET_FIELDS:
            if path[0] in runtime and not _get(runtime, path) and _get(previous, path):
                _set(runtime, path, _get(previous, path))  # vacío = conservar el anterior
        if strict:
            effective = runtime_view(self.current(conn))
            for path in self.locked():
                keys = tuple(path.split("."))
                if _get(runtime, keys) != _get(effective, keys):
                    raise ConfigError(self.lock_message(path), path)
        full = self.validate(runtime)
        # Solo se guarda lo que difiere del predeterminado y no está bloqueado: así cada campo sabe
        # de dónde viene y un campo que se quite de config.json vuelve a ser editable.
        minimal = diff_overrides(self.defaults(), runtime_view(full))
        for path in self.locked():
            minimal = drop_path(minimal, path)
        repo.put(conn, self.key, minimal, username)
        return minimal

    def reset_path(self, conn: Connection, dotted: str, username: str | None) -> None:
        """Vuelve un ajuste a su valor predeterminado."""
        if self.lock_of(dotted):
            raise ConfigError(self.lock_message(dotted), dotted)
        remaining = drop_path(self.overrides(conn), dotted)
        self.validate(remaining)
        repo.put(conn, self.key, remaining, username)

    def reset(self, conn: Connection, username: str | None) -> None:
        """Descarta todos los ajustes web: vuelven los predeterminados (salvo lo bloqueado)."""
        repo.put(conn, self.key, {}, username)

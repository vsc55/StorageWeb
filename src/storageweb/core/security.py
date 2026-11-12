"""Utilidades de seguridad independientes del framework web."""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from pathlib import Path

from ..i18n import _

UPLOAD_TMP_PREFIX = ".sw-upload-"
IS_WINDOWS = os.name == "nt"

_INVALID_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


class PathError(Exception):
    """Ruta fuera de la raíz permitida o no válida."""


def safe_filename(name: str) -> str:
    """Sanea un nombre de archivo/carpeta conservando acentos y espacios."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = _INVALID_CHARS.sub("_", name).strip().rstrip(". ")
    if name in ("", ".", "..") or name.startswith(UPLOAD_TMP_PREFIX):
        raise ValueError(_("Invalid file name"))
    if IS_WINDOWS and name.split(".")[0].upper() in _WIN_RESERVED:
        raise ValueError(_("Reserved name on Windows"))
    if len(name.encode("utf-8")) > 255:
        stem, dot, ext = name.rpartition(".")
        if not dot or len(ext) > 16:
            stem, ext = name, ""
        budget = 255 - len(ext.encode("utf-8")) - (1 if ext else 0)
        stem = stem.encode("utf-8")[:budget].decode("utf-8", "ignore")
        name = f"{stem}.{ext}" if ext else stem
    return name


def safe_username_for_path(username: str) -> str:
    """Nombre de usuario apto para usarse como nombre de carpeta."""
    cleaned = re.sub(r"[^A-Za-z0-9._@-]", "_", unicodedata.normalize("NFC", username.lower()))
    cleaned = cleaned.strip(".")
    if not cleaned:
        raise ValueError(_("Invalid user name for a folder"))
    return cleaned


def resolve_inside(base: Path, sub: str) -> Path:
    """Devuelve base/sub garantizando que no escapa de base (incluidos symlinks)."""
    base = base.resolve()
    parts = [p for p in sub.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PathError(sub)
    target = base.joinpath(*parts).resolve() if parts else base
    if target != base and base not in target.parents:
        raise PathError(sub)
    return target


def resolve_entry(base: Path, sub: str) -> Path:
    """Como resolve_inside pero sin seguir el symlink del último elemento (borrar/renombrar)."""
    parts = [p for p in sub.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or parts[-1] == "..":
        raise PathError(sub)
    entry = resolve_inside(base, "/".join(parts[:-1])) / parts[-1]
    if not (entry.exists() or entry.is_symlink()):
        raise PathError(sub)
    return entry


class LoginThrottle:
    """Bloqueo temporal tras N intentos fallidos (por IP y por usuario). En memoria."""

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900):
        self.max_failures = max_failures
        self.lockout = lockout_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def configure(self, max_failures: int, lockout_seconds: int) -> None:
        self.max_failures = max_failures
        self.lockout = lockout_seconds

    @staticmethod
    def _keys(ip: str, username: str) -> list[str]:
        return [f"ip:{ip}", f"user:{username.lower()}"]

    def _prune(self, key: str, now: float) -> list[float]:
        items = [t for t in self._fails.get(key, []) if now - t < self.lockout]
        if items:
            self._fails[key] = items
        else:
            self._fails.pop(key, None)
        return items

    def is_blocked(self, ip: str, username: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._prune(k, now)) >= self.max_failures for k in self._keys(ip, username))

    def failure(self, ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in self._keys(ip, username):
                self._prune(k, now)
                self._fails.setdefault(k, []).append(now)

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._fails.pop(f"user:{username.lower()}", None)

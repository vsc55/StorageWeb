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


# Lo que Windows trata como especial en un nombre (como os.path.isreserved de Python 3.13): un nombre que acaba en
# punto o espacio (Windows los quita: «secreto.md.» abre «secreto.md»), «:» (flujos de NTFS: «secreto.md::$DATA»
# abre el contenido), comodines y los dispositivos (CON, NUL…, también con extensión: «con.txt»)
_WIN_SPECIAL_CHARS = re.compile(r'[\x00-\x1f:*?"<>|]')
_WIN_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                *(f"{port}{n}" for port in ("COM", "LPT") for n in (*"0123456789", "\u00b9", "\u00b2", "\u00b3"))}
_SHORT_NAME = re.compile(r"~\d")


def windows_reserved(name: str) -> bool:
    """``True`` si ``name`` (un nombre, sin barras) no es lo que parece en Windows: abriría otro archivo, un flujo
    de NTFS o un dispositivo. Esas rutas se rechazan en el disco de un servidor Windows y en SMB, porque se saltarían
    los «ocultos para todos» (``storage.hidden``) o dejarían colgada la petición (``CON``)."""
    if not name or name in (".", ".."):
        return False
    if name[-1] in ". " or _WIN_SPECIAL_CHARS.search(name):
        return True
    return name.split(".")[0].rstrip(" ").upper() in _WIN_DEVICES


def check_windows_parts(parts) -> None:
    """:class:`PathError` si algún trozo de la ruta es un nombre especial de Windows (:func:`windows_reserved`)."""
    for part in parts:
        if windows_reserved(part):
            raise PathError(part)


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
    if IS_WINDOWS:
        check_windows_parts(parts)
    target = base.joinpath(*parts).resolve() if parts else base
    if target != base and base not in target.parents:
        raise PathError(sub)
    if IS_WINDOWS and any(_SHORT_NAME.search(p) for p in parts) and target != base:
        # Un nombre corto de 8.3 («SECRET~1.MD») abre el largo («secreto.md») sin que lo vea storage.hidden: solo
        # vale si es el nombre de verdad
        real = target.relative_to(base).parts
        if [p.casefold() for p in real] != [p.casefold() for p in parts]:
            raise PathError(sub)
    return target


def resolve_entry(base: Path, sub: str) -> Path:
    """Como resolve_inside pero sin seguir el symlink del último elemento (borrar/renombrar)."""
    parts = [p for p in sub.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or parts[-1] == "..":
        raise PathError(sub)
    if IS_WINDOWS:
        check_windows_parts(parts)
    entry = resolve_inside(base, "/".join(parts[:-1])) / parts[-1]
    if not (entry.exists() or entry.is_symlink()):
        raise PathError(sub)
    return entry


class LoginThrottle:
    """Bloqueo temporal tras N intentos fallidos (por IP y por usuario). En memoria.

    ``scope`` separa contadores: los fallos de la unidad de red (``"dav"``) no bloquean el inicio de
    sesión en la web, y al revés (una unidad mal configurada reintenta sola y bloquearía al usuario).
    """

    def __init__(self, max_failures: int = 5, lockout_seconds: int = 900):
        self.max_failures = max_failures
        self.lockout = lockout_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def configure(self, max_failures: int, lockout_seconds: int) -> None:
        self.max_failures = max_failures
        self.lockout = lockout_seconds

    @staticmethod
    def _keys(ip: str, username: str, scope: str = "") -> list[str]:
        prefix = f"{scope}:" if scope else ""
        return [f"{prefix}ip:{ip}", f"{prefix}user:{username.lower()}"]

    def _prune(self, key: str, now: float) -> list[float]:
        items = [t for t in self._fails.get(key, []) if now - t < self.lockout]
        if items:
            self._fails[key] = items
        else:
            self._fails.pop(key, None)
        return items

    def is_blocked(self, ip: str, username: str, scope: str = "") -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._prune(k, now)) >= self.max_failures for k in self._keys(ip, username, scope))

    def failure(self, ip: str, username: str, scope: str = "") -> None:
        now = time.monotonic()
        with self._lock:
            for k in self._keys(ip, username, scope):
                self._prune(k, now)
                self._fails.setdefault(k, []).append(now)

    def success(self, ip: str, username: str, scope: str = "") -> None:
        with self._lock:
            self._fails.pop(self._keys(ip, username, scope)[1], None)

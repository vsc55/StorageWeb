"""Patrones de archivos y carpetas, como los de ``.gitignore``. Los usa ``storage.hidden`` (ocultos para todos:
no se listan, no se pueden abrir ni crear; ver ``core/storage.is_hidden``) y se validan al cargar la configuración.

Los patrones son como los de ``.gitignore`` (y los del ``.storagewebignore`` de la extensión de VS Code),
sobre la ruta dentro de cada carpeta de StorageWeb (la personal o una compartida):

- ``Thumbs.db``, ``*.tmp``: ese nombre en cualquier sitio.
- ``carpeta/``: solo carpetas con ese nombre (y todo lo de dentro).
- ``/algo`` o ``a/b``: desde la raíz de la carpeta de StorageWeb.
- ``*`` (dentro de un nombre), ``**`` (cualquier número de carpetas), ``?`` y ``[abc]``.

Una carpeta oculta oculta todo lo que tiene dentro. Las negaciones (``!``) no se admiten.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Callable, Iterable

from .i18n import _

MAX_PATTERNS = 200


class PatternError(ValueError):
    pass


def _glob_to_regex(pattern: str) -> str:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and pattern[i + 1:i + 2] == "*":
            if pattern[i + 2:i + 3] == "/":
                out.append("(?:.*/)?")
                i += 3
            else:
                out.append(".*")
                i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[" and "]" in pattern[i + 2:]:
            end = pattern.index("]", i + 2)
            body = pattern[i + 1:end]
            body = ("^" + body[1:]) if body.startswith("!") else body
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = end
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def normalize(patterns: Iterable[str]) -> list[str]:
    """Limpia y valida la lista (lo que se guarda). Lanza PatternError con un mensaje para el usuario."""
    clean: list[str] = []
    for raw in patterns:
        line = str(raw).strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            raise PatternError(_("Exceptions with «!» are not supported: %(pattern)s", pattern=line))
        if "\\" in line or ".." in line.split("/") or any(ord(ch) < 32 for ch in line):
            raise PatternError(_("Invalid pattern: %(pattern)s", pattern=line))
        if line.strip("/*") == "":
            raise PatternError(_("This pattern would hide everything: %(pattern)s", pattern=line))
        if line not in clean:
            clean.append(line)
    if len(clean) > MAX_PATTERNS:
        raise PatternError(_("Too many patterns (at most %(n)s).", n=MAX_PATTERNS))
    return clean


@lru_cache(maxsize=32)
def _compile(patterns: tuple[str, ...]) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    """(patrones para cualquier ruta, patrones solo para carpetas), cada grupo en una expresión."""
    any_kind, dirs_only = [], []
    for line in patterns:
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = line.startswith("/") or "/" in line
        line = line.lstrip("/")
        regex = _glob_to_regex(line)
        if not anchored and not line.startswith("**/"):
            regex = "(?:.*/)?" + regex
        (dirs_only if dir_only else any_kind).append(regex)
    flags = re.IGNORECASE  # como en Windows y en macOS: «thumbs.db» también
    return (re.compile("^(?:" + "|".join(any_kind) + ")$", flags) if any_kind else None,
            re.compile("^(?:" + "|".join(dirs_only) + ")$", flags) if dirs_only else None)


def matcher(patterns: Iterable[str]) -> Callable[[str, bool], bool]:
    """Función ``(ruta, es_carpeta) → oculto``. Una ruta está oculta si lo está ella o alguna carpeta de encima."""
    any_kind, dirs_only = _compile(tuple(patterns))
    if any_kind is None and dirs_only is None:
        return lambda rel, is_dir=False: False

    def hidden(rel: str, is_dir: bool = False) -> bool:
        parts = [p for p in rel.split("/") if p]
        for i in range(1, len(parts) + 1):
            path = "/".join(parts[:i])
            as_dir = is_dir or i < len(parts)
            if (any_kind and any_kind.match(path)) or (as_dir and dirs_only and dirs_only.match(path)):
                return True
        return False
    return hidden


def of(cfg: dict) -> Callable[[str, bool], bool]:
    """El matcher de la configuración (``storage.hidden``)."""
    return matcher(cfg["storage"].get("hidden") or ())

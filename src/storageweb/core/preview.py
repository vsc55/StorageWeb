"""Visor de archivos de texto y Markdown (``/view/…``, ``web/views/files.py``).

Qué se puede ver (:func:`kind_of`), leerlo con un límite de tamaño y averiguar si es texto
(:func:`read_text`), y el anterior y el siguiente de la carpeta (:func:`neighbours`). El Markdown se
convierte a HTML en ``core/markdown.py``; aquí solo se decide qué es cada archivo.

- ``markdown``: se ve renderizado (o su código).
- ``text``: texto o código, con números de línea.
- ``markup``: HTML y SVG. **Siempre como código**: abrirlos como página ejecutaría lo que lleven dentro
  con la sesión del usuario.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from . import backends
from ..settings import DEFAULTS
from .security import PathError

MAX_BYTES = 2 * 1024 * 1024      # sin ajustes (preview.max_mb); más grande: se descarga
SNIFF_BYTES = 8192               # un byte nulo en este principio: no es texto

# Qué es cada extensión de la lista que se abre (preview.extensions; la de serie, PREVIEW_EXTENSIONS): las de
# Markdown se ven con formato, las de HTML y SVG siempre como código y cualquier otra, como texto
MARKDOWN = frozenset({"md", "markdown", "mdown", "mkd", "mkdn"})
MARKUP = frozenset({"html", "htm", "xhtml", "svg"})
# Sin extensión, por su nombre: se abren siempre (salvo con el visor desactivado)
TEXT_NAMES = frozenset({"readme", "license", "licence", "copying", "authors", "changelog", "makefile",
                        "dockerfile", "containerfile", "vagrantfile", "procfile", "gemfile", "jenkinsfile",
                        ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore"})
LOG = frozenset({"log"})
IMAGES = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"})


def extension(name: str) -> str:
    return PurePosixPath(name).suffix.lstrip(".").lower()


def kind_of(name: str, options: dict | None = None) -> str | None:
    """``markdown``, ``text`` o ``markup`` si el visor lo abre; si no, ``None`` (se descarga). ``options`` es
    ``cfg["preview"]`` (sin ellos, los de serie): el visor desactivado, la lista de extensiones que se abren y
    la de las que nunca."""
    options = options if options is not None else DEFAULTS["preview"]
    ext = extension(name)
    blocked = options.get("blocked_extensions", ())
    # Un archivo «punto» sin extensión (.env, .npmrc) cuenta como la suya: .env se bloquea con «env»
    dotname = name.lower()[1:] if not ext and name.startswith(".") else ""
    if not options.get("enabled", True) or ext in blocked or (dotname and dotname in blocked):
        return None
    if ext not in options.get("extensions", ()):
        return "text" if not ext and name.lower() in TEXT_NAMES else None
    if ext in MARKDOWN:
        return "markdown"
    if ext in MARKUP:
        return "markup"
    return "text"


def is_image(name: str) -> bool:
    return extension(name) in IMAGES


@dataclass
class Content:
    text: str | None = None      # None: no se puede ver (``reason``)
    encoding: str = "utf-8"      # ``utf-8`` o ``cp1252`` (ni UTF-8 ni binario: Windows occidental)
    reason: str = ""             # ``too_large`` | ``binary``

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n") if self.text is not None else []


def read_text(backend, rel: str, size: int, limit: int = MAX_BYTES) -> Content:
    """El archivo como texto, si cabe en ``limit`` y no es binario. Lee como mucho ``limit`` bytes."""
    if size > limit:
        return Content(reason="too_large")
    data = _read(backend, rel, limit)
    if len(data) > limit:
        return Content(reason="too_large")
    if b"\x00" in data[:SNIFF_BYTES]:
        return Content(reason="binary")
    try:
        text, encoding = data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = data.decode("cp1252", errors="replace"), "cp1252"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return Content(text=text, encoding=encoding)


def _read(backend, rel: str, limit: int) -> bytes:
    local = backend.local_path(rel)
    if local is not None:
        with open(local, "rb") as fh:
            return fh.read(limit + 1)
    fh, _size, _mtime = backend.open(rel)
    try:
        return fh.read(limit + 1)
    finally:
        fh.close()


# El nivel en mayúsculas como palabra (ERROR), o en cualquier forma entre corchetes o como level=…
_ERROR = re.compile(r"\b(?:ERROR|CRITICAL|FATAL|SEVERE)\b")
_ERROR_ANY_CASE = re.compile(r"\[(?:error|critical|fatal)\]|\blevel=(?:error|critical|fatal)\b", re.I)
_WARN = re.compile(r"\b(?:WARN|WARNING)\b")
_WARN_ANY_CASE = re.compile(r"\[(?:warn|warning)\]|\blevel=(?:warn|warning)\b", re.I)


def log_level(line: str) -> str:
    """``error`` / ``warn`` / ``""`` para colorear las líneas de un ``.log``. Solo el nivel escrito como tal
    (``ERROR``, ``[error]``, ``level=error``): «1 aviso, 1 error» en un resumen no es una línea de error."""
    low = line.lower()
    if not any(word in low for word in ("err", "warn", "crit", "fatal", "severe")):
        return ""     # la mayoría de las líneas: sin buscar con las expresiones (rendimiento)
    if _ERROR.search(line) or _ERROR_ANY_CASE.search(line):
        return "error"
    if _WARN.search(line) or _WARN_ANY_CASE.search(line):
        return "warn"
    return ""


def neighbours(entries: list[dict], rel: str, options: dict | None = None) -> tuple[dict | None, dict | None]:
    """El archivo que se puede ver anterior y siguiente a ``rel`` en el listado de su carpeta."""
    files = [e for e in entries if not e["is_dir"] and kind_of(e["name"], options)]
    for i, e in enumerate(files):
        if e["rel"] == rel:
            return (files[i - 1] if i > 0 else None), (files[i + 1] if i + 1 < len(files) else None)
    return None, None


def resolve(base_rel: str, target: str) -> str | None:
    """Una ruta relativa del documento (``../img/a.png``, ``/docs/b.md``) dentro de su raíz, o ``None`` si
    sale de ella o no es una ruta."""
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        parent = str(PurePosixPath(base_rel).parent)
        joined = f"{'' if parent == '.' else parent + '/'}{path}"
    parts: list[str] = []
    for part in joined.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    try:
        return backends.clean_rel("/".join(parts)) if parts else None
    except PathError:
        return None

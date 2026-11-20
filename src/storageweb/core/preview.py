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
HIGHLIGHT_MAX_BYTES = 1024 * 1024    # más grande, el código se ve sin colores (colorearlo bloquearía la página)
EDITOR_HIGHLIGHT_MAX_BYTES = 256 * 1024   # en el editor se colorea en cada pausa al escribir: menos

# Colores del código (preview.highlight, highlight.js en el navegador): extensión → lenguaje de highlight.js.
# Lo que no está aquí (texto, CSV, logs…) se ve sin colores
LANGUAGES = {
    **dict.fromkeys(("py", "pyw", "pyi"), "python"), "php": "php",
    **dict.fromkeys(("js", "mjs", "cjs", "jsx"), "javascript"), **dict.fromkeys(("ts", "tsx"), "typescript"),
    **dict.fromkeys(("json", "jsonc"), "json"), **dict.fromkeys(("yml", "yaml"), "yaml"),
    **dict.fromkeys(("xml", "xsd", "xsl", "xslt", "svg", "html", "htm", "xhtml", "plist", "csproj", "props"), "xml"),
    "css": "css", **dict.fromkeys(("scss", "sass"), "scss"), "less": "less", "sql": "sql",
    **dict.fromkeys(("sh", "bash", "zsh", "fish"), "bash"),
    **dict.fromkeys(("ini", "cfg", "conf", "config", "toml", "properties", "reg"), "ini"),
    **dict.fromkeys(("md", "markdown", "mdown", "mkd", "mkdn"), "markdown"),
    "java": "java", **dict.fromkeys(("c", "h"), "c"), **dict.fromkeys(("cc", "cpp", "cxx", "hpp", "hh"), "cpp"),
    "cs": "csharp", "go": "go", "rs": "rust", "rb": "ruby", **dict.fromkeys(("kt", "kts", "gradle"), "kotlin"),
    "swift": "swift", **dict.fromkeys(("diff", "patch"), "diff"), "lua": "lua", **dict.fromkeys(("pl", "pm"), "perl"),
    "r": "r", "vb": "vbnet", "vbs": "vbscript", **dict.fromkeys(("ps1", "psm1", "psd1"), "powershell"),
    **dict.fromkeys(("bat", "cmd"), "dos"), **dict.fromkeys(("graphql", "gql"), "graphql"), "mk": "makefile",
    "dockerfile": "dockerfile",
}
# Cómo se llama cada lenguaje en la cabecera del visor (los que no están: con mayúscula inicial)
LANGUAGE_LABELS = {"javascript": "JavaScript", "typescript": "TypeScript", "php": "PHP", "json": "JSON",
                   "yaml": "YAML", "xml": "XML", "css": "CSS", "scss": "SCSS", "less": "Less", "sql": "SQL",
                   "ini": "INI", "csharp": "C#", "cpp": "C++", "vbnet": "VB.NET", "vbscript": "VBScript",
                   "powershell": "PowerShell", "dos": "Batch", "graphql": "GraphQL", "bash": "Shell",
                   "objectivec": "Objective-C", "r": "R", "c": "C", "go": "Go", "nginx": "nginx"}
# Cómo se comenta en cada lenguaje (el editor: Comentar, Ctrl+/): (inicio, fin); sin fin = comentario de línea
_HASH = ("python", "bash", "yaml", "ruby", "perl", "r", "powershell", "dockerfile", "nginx", "apache", "makefile")
_SLASH = ("javascript", "typescript", "java", "c", "cpp", "csharp", "go", "rust", "kotlin", "swift", "php", "scss",
          "less", "objectivec", "graphql")
COMMENTS = {**dict.fromkeys(_HASH, ("#", "")), **dict.fromkeys(_SLASH, ("//", "")), "graphql": ("#", ""),
            "sql": ("--", ""), "lua": ("--", ""), "ini": (";", ""), "vbnet": ("'", ""), "vbscript": ("'", ""),
            "dos": ("REM", ""), "css": ("/*", "*/"), "xml": ("<!--", "-->"), "markdown": ("<!--", "-->")}
# Sin extensión que lo diga, por el nombre
LANGUAGE_NAMES = {"dockerfile": "dockerfile", "containerfile": "dockerfile", "makefile": "makefile",
                  "nginx.conf": "nginx", ".htaccess": "apache", "httpd.conf": "apache", "apache2.conf": "apache",
                  ".bashrc": "bash", ".profile": "bash", ".zshrc": "bash", ".gitconfig": "ini", ".editorconfig": "ini"}
# Lenguajes que no trae highlight.min.js (los comunes): su fichero aparte, en static/vendor/highlight/languages/
EXTRA_LANGUAGES = frozenset({"apache", "dockerfile", "dos", "nginx", "powershell", "vbscript"})
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


def language_of(name: str) -> str:
    """El lenguaje de highlight.js para colorear el código, o ``""`` (sin colores: texto, CSV, logs…)."""
    low = name.lower()
    return LANGUAGE_NAMES.get(low) or LANGUAGES.get(extension(name), "")


def language_label(lang: str) -> str:
    return LANGUAGE_LABELS.get(lang) or lang.capitalize()


def is_image(name: str) -> bool:
    return extension(name) in IMAGES


@dataclass
class Content:
    text: str | None = None      # None: no se puede ver (``reason``)
    encoding: str = "utf-8"      # ``utf-8`` o ``cp1252`` (ni UTF-8 ni binario: Windows occidental)
    reason: str = ""             # ``too_large`` | ``binary``
    crlf: bool = False           # el original usaba finales de línea de Windows (el editor los conserva)
    final_newline: bool = False  # el original acababa en salto de línea
    bom: bool = False            # el original empezaba con la marca UTF-8 (BOM)

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
    crlf = b"\r\n" in data
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    final = text.endswith("\n")
    if final:
        text = text[:-1]
    return Content(text=text, encoding=encoding, crlf=crlf, final_newline=final,
                   bom=data.startswith(b"\xef\xbb\xbf"))


def encode_text(text: str, *, crlf: bool, final_newline: bool, bom: bool = False) -> bytes:
    """Lo escrito en el editor, guardado como el original: UTF-8, sus finales de línea y su salto final."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if final_newline and not text.endswith("\n"):
        text += "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


@dataclass
class Window:
    """Un trozo de un archivo de texto demasiado grande para verlo entero (los logs, por el final)."""
    text: str | None
    encoding: str
    start: int          # primer byte que se ve (al principio de una línea)
    end: int            # byte siguiente al último que se ve (al final de una línea)
    size: int
    reason: str = ""    # ``binary`` si el trozo no es texto

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n") if self.text is not None else []

    @property
    def at_start(self) -> bool:
        return self.start == 0

    @property
    def at_end(self) -> bool:
        return self.end >= self.size


def read_window(backend, rel: str, size: int, start: int | None, limit: int = MAX_BYTES) -> Window:
    """``limit`` bytes del archivo desde ``start`` (``None`` = los últimos), recortados a líneas enteras: si no
    empieza al principio, desde el primer salto de línea; si no acaba al final, hasta el último. Solo se lee
    ese trozo (en un almacenamiento remoto, con una petición por rango)."""
    if start is None:
        start = max(0, size - limit)
    start = min(max(0, start), max(0, size - 1))
    data = _read_at(backend, rel, start, limit)
    begin = 0
    if start > 0:
        cut = data.find(b"\n")
        begin = cut + 1 if cut >= 0 else 0
    finish = len(data)
    if start + len(data) < size:
        cut = data.rfind(b"\n")
        finish = cut + 1 if cut >= begin else len(data)
    chunk = data[begin:finish]
    window = Window(None, "utf-8", start + begin, start + finish, size)
    if b"\x00" in chunk[:SNIFF_BYTES]:
        window.reason = "binary"
        return window
    try:
        text = chunk.decode("utf-8-sig" if window.start == 0 else "utf-8")
    except UnicodeDecodeError:
        text, window.encoding = chunk.decode("cp1252", errors="replace"), "cp1252"
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    window.text = text[:-1] if text.endswith("\n") else text
    return window


def _read_at(backend, rel: str, start: int, limit: int) -> bytes:
    local = backend.local_path(rel)
    if local is not None:
        with open(local, "rb") as fh:
            fh.seek(start)
            return fh.read(limit)
    fh, _size, _mtime = backend.open(rel)
    try:
        if start:
            fh.seek(start)
        data = bytearray()
        while len(data) < limit:      # un lector remoto puede dar menos de lo pedido en cada lectura
            piece = fh.read(limit - len(data))
            if not piece:
                break
            data += piece
        return bytes(data)
    finally:
        fh.close()


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

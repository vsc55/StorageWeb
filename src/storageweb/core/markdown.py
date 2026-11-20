"""Markdown a HTML seguro, sin dependencias (lo usa el visor de archivos, ``core/preview.py``).

**Seguro por construcción:** todo el texto del documento se escapa y solo salen las etiquetas que genera este
módulo. El HTML que traiga el documento se ve como texto. Las direcciones de los enlaces y de las imágenes las
decide quien llama (``link``/``image``), que puede rechazarlas (``None``): así nunca sale un ``javascript:``
ni se carga una imagen de fuera. Los ``id`` de los encabezados llevan el prefijo ``h-`` (no pisan los de la
página) y los enlaces internos (``#calendario``) se traducen a ellos.

Cubre lo habitual de CommonMark y de GitHub: encabezados (``#`` y subrayados), párrafos, énfasis, tachado,
código en línea y en bloque, citas, listas anidadas y de tareas, tablas, líneas horizontales, enlaces (también
por referencia y direcciones sueltas) e imágenes.
"""
from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from ..i18n import _

Resolver = Callable[[str], "str | None"]
MAX_DEPTH = 16          # citas y listas anidadas: más allá, el resto se ve como texto
HEADING_PREFIX = "h-"


@dataclass
class Rendered:
    html: str
    toc: list[tuple[int, str, str]] = field(default_factory=list)   # (nivel, texto, id) de los h2 y h3
    diagrams: int = 0                                                # bloques ```mermaid```


def render(text: str, *, link: Resolver | None = None, image: Resolver | None = None) -> Rendered:
    """El documento en HTML. ``link(url)``/``image(url)`` devuelven la dirección que se usará o ``None``."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "\ufffd").split("\n")
    refs: dict[str, tuple[str, str]] = {}
    lines = _collect_references(lines, refs)
    state = _State(link or (lambda url: None), image or (lambda url: None), refs)
    body = _Blocks(state).render(lines, depth=0)
    return Rendered(body, state.toc, state.diagrams)


# --------------------------------------------------------------------------- utilidades

def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def slug(text: str) -> str:
    """Como GitHub: minúsculas, sin acentos, guiones; para los ``id`` de los encabezados."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "seccion"


def _plain(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


_REF_DEF = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*<?([^\s>]+)>?(?:\s+[\"'(](.*)[\"')])?\s*$")


def _collect_references(lines: list[str], refs: dict) -> list[str]:
    """Quita las definiciones ``[nombre]: dirección "título"`` (fuera de bloques de código) y las guarda."""
    out, fence = [], None
    for line in lines:
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not line.strip()[len(marker):].strip():
                fence = None
            out.append(line)
            continue
        d = _REF_DEF.match(line) if fence is None else None
        if d:
            refs.setdefault(d.group(1).strip().lower(), (d.group(2), d.group(3) or ""))
        else:
            out.append(line)
    return out


class _State:
    def __init__(self, link: Resolver, image: Resolver, refs: dict):
        self.link, self.image, self.refs = link, image, refs
        self.toc: list[tuple[int, str, str]] = []
        self.ids: dict[str, int] = {}
        self.diagrams = 0

    def heading_id(self, text: str) -> str:
        base = HEADING_PREFIX + slug(text)
        n = self.ids.get(base, 0)
        self.ids[base] = n + 1
        return base if n == 0 else f"{base}-{n}"

    def href(self, url: str) -> str | None:
        url = url.strip()
        if url.startswith("#"):
            return "#" + HEADING_PREFIX + slug(html.unescape(url[1:]))
        return self.link(url)


# --------------------------------------------------------------------------- bloques

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`\s]*)")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_LIST = re.compile(r"^( {0,3})([-*+]|\d{1,9}[.)])([ \t]+(.*))?$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_TABLE_SEP = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_TASK = re.compile(r"^\[([ xX])\][ \t]+")
_LANG = re.compile(r"[\w+#.-]{1,30}")


class _Blocks:
    def __init__(self, state: _State):
        self.s = state

    def render(self, lines: list[str], depth: int, tight: bool = False) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i].expandtabs(4)
            if not line.strip():
                i += 1
                continue
            fence = _FENCE.match(line)
            if fence:
                i = self._fenced(lines, i, fence, out)
                continue
            atx = _ATX.match(line)
            if atx:
                self._heading(len(atx.group(1)), atx.group(2) or "", out)
                i += 1
                continue
            if _HR.match(line):
                out.append("<hr>")
                i += 1
                continue
            if _QUOTE.match(line) and depth < MAX_DEPTH:
                i = self._quote(lines, i, depth, out)
                continue
            item = _LIST.match(line)
            if item and depth < MAX_DEPTH and (item.group(4) or "").strip():
                i = self._list(lines, i, depth, out)
                continue
            if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
                i = self._table(lines, i, out)
                continue
            if line.startswith("    "):
                i = self._indented(lines, i, out)
                continue
            i = self._paragraph(lines, i, out, tight)
        return "\n".join(out)

    # -- cada tipo de bloque

    def _fenced(self, lines, i, fence, out) -> int:
        marker, lang = fence.group(1), fence.group(2)
        indent = len(lines[i]) - len(lines[i].lstrip(" "))
        body, i = [], i + 1
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(marker[0] * len(marker)) and not stripped.lstrip(marker[0]).strip():
                i += 1
                break
            body.append(re.sub(rf"^ {{0,{indent}}}", "", lines[i]))
            i += 1
        cls = f' class="language-{_esc(lang)}"' if lang and _LANG.fullmatch(lang) else ""
        block = f"<pre><code{cls}>{_esc(chr(10).join(body))}</code></pre>"
        if lang.lower() == "mermaid":
            # Lo dibuja el visor en un marco aislado (viewer.js → /diagram-frame); sin JavaScript, se ve el código
            self.s.diagrams += 1
            block = f'<div class="md-diagram">{block}</div>'
        out.append(block)
        return i

    def _heading(self, level: int, text: str, out) -> None:
        inner = self._inline(text.strip())
        plain = _plain(inner)
        hid = self.s.heading_id(plain)
        if level in (2, 3):
            self.s.toc.append((level, plain, hid))
        out.append(f'<h{level} id="{hid}">{inner}</h{level}>')

    def _quote(self, lines, i, depth, out) -> int:
        body = []
        while i < len(lines):
            m = _QUOTE.match(lines[i].expandtabs(4))
            if m:
                body.append(m.group(1))
            elif lines[i].strip() and body and body[-1].strip() and not _starts_block(lines[i]):
                body.append(lines[i])          # continuación perezosa de un párrafo de la cita
            else:
                break
            i += 1
        out.append(f"<blockquote>\n{self.render(body, depth + 1)}\n</blockquote>")
        return i

    def _list(self, lines, i, depth, out) -> int:
        first = _LIST.match(lines[i].expandtabs(4))
        ordered = first.group(2)[-1] in ".)" and first.group(2)[:-1].isdigit()
        kind = _kind(first)
        start = int(first.group(2)[:-1]) if ordered else 1
        items: list[list[str]] = []
        loose = False
        while i < len(lines):
            line = lines[i].expandtabs(4)
            m = _LIST.match(line)
            if not m or _kind(m) != kind:
                break
            indent = len(m.group(1)) + len(m.group(2)) + (len(m.group(3)) - len(m.group(3).lstrip()) if m.group(3) else 1)
            item = [m.group(4) or ""]
            i += 1
            blank = False
            while i < len(lines):
                raw = lines[i].expandtabs(4)
                if not raw.strip():
                    blank = True
                    item.append("")
                    i += 1
                    continue
                lead = len(raw) - len(raw.lstrip(" "))
                if lead >= indent:
                    if blank and item[-1] == "" and any(x.strip() for x in item[:-1]):
                        loose = True
                    item.append(raw[indent:])
                    blank = False
                    i += 1
                    continue
                if not blank and not _starts_block(raw) and not _LIST.match(raw):
                    item.append(raw.strip())       # continuación perezosa
                    i += 1
                    continue
                break
            while item and not item[-1].strip():
                item.pop()
            items.append(item)
            if blank and i < len(lines):
                nxt = _LIST.match(lines[i].expandtabs(4))
                if nxt and _kind(nxt) == kind:
                    loose = True
        tag = "ol" if ordered else "ul"
        attr = f' start="{start}"' if ordered and start != 1 else ""
        parts = []
        for item in items:
            check = ""
            task = _TASK.match(item[0]) if item else None
            if task:
                checked = " checked" if task.group(1) in "xX" else ""
                check = f'<input type="checkbox" disabled{checked}> '
                item = [item[0][task.end():], *item[1:]]
            inner = self.render(item, depth + 1, tight=not loose)
            cls = ' class="task"' if task else ""
            parts.append(f"<li{cls}>{check}{inner}</li>")
        out.append(f"<{tag}{attr}>\n" + "\n".join(parts) + f"\n</{tag}>")
        return i

    def _table(self, lines, i, out) -> int:
        header = _cells(lines[i])
        aligns = []
        for cell in _cells(lines[i + 1]):
            c = cell.strip()
            aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":")
                          else "left" if c.startswith(":") else "")
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(_cells(lines[i]))
            i += 1
        width = len(header)

        def row(cells, tag):
            cells = (cells + [""] * width)[:width]
            return "<tr>" + "".join(
                f"<{tag}{_align(aligns[k] if k < len(aligns) else '')}>{self._inline(c.strip())}</{tag}>"
                for k, c in enumerate(cells)) + "</tr>"
        body = "\n".join(row(r, "td") for r in rows)
        out.append(f'<div class="md-table"><table>\n<thead>{row(header, "th")}</thead>\n'
                   f"<tbody>\n{body}\n</tbody>\n</table></div>")
        return i

    def _indented(self, lines, i, out) -> int:
        body = []
        while i < len(lines) and (lines[i].expandtabs(4).startswith("    ") or not lines[i].strip()):
            body.append(lines[i].expandtabs(4)[4:])
            i += 1
        while body and not body[-1].strip():
            body.pop()
        out.append(f"<pre><code>{_esc(chr(10).join(body))}</code></pre>")
        return i

    def _paragraph(self, lines, i, out, tight) -> int:
        body = [_para_line(lines[i].expandtabs(4))]
        i += 1
        while i < len(lines) and lines[i].strip():
            line = lines[i].expandtabs(4)
            setext = _SETEXT.match(line)
            if setext:
                self._heading(1 if setext.group(1)[0] == "=" else 2, "\n".join(body), out)
                return i + 1
            if _starts_block(line):
                break
            body.append(_para_line(line))
            i += 1
        inner = self._inline("\n".join(body))
        out.append(inner if tight else f"<p>{inner}</p>")
        return i

    def _inline(self, text: str) -> str:
        return _Inline(self.s).render(text)


def _kind(m) -> str:
    """El tipo de una lista: su viñeta (``-``, ``*``, ``+``) o el signo tras el número (``.`` o ``)``)."""
    marker = m.group(2)
    return marker[-1] if marker[:-1].isdigit() else marker


def _para_line(line: str) -> str:
    """Sin la sangría; los dos espacios del final se quedan (salto de línea forzado)."""
    line = line.lstrip()
    return line.rstrip() + "  " if line.endswith("  ") else line.rstrip()


def _starts_block(line: str) -> bool:
    line = line.expandtabs(4)
    m = _LIST.match(line)
    return bool(_FENCE.match(line) or _ATX.match(line) or _HR.match(line) or _QUOTE.match(line)
                or (m and m.group(4) and (not m.group(2)[0].isdigit() or m.group(2)[:-1] == "1")))


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _align(value: str) -> str:
    return f' class="al-{value}"' if value else ""


# --------------------------------------------------------------------------- en línea

_CODE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)", re.S)
_ESCAPE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^\s<>]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)>")
_BARE_URL = re.compile(r"(?<![\w/\"'=\x00])(https?://[^\s<>\x00]*[^\s<>\x00.,;:!?)\]'\"])")
_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_EM_STAR = re.compile(r"\*(?=[^\s*])(.+?)(?<=[^\s*])\*", re.S)
_EM_UNDER = re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", re.S)
_DEL = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
_HARD_BREAK = re.compile(r"(?: {2,}|\\)\n")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


class _Inline:
    def __init__(self, state: _State, slots: list[str] | None = None):
        self.s = state
        # El texto de un enlace se convierte con los mismos huecos: ya puede traer apartados los suyos (`código`)
        self.slots: list[str] = [] if slots is None else slots

    def keep(self, fragment: str) -> str:
        self.slots.append(fragment)
        return f"\x00{len(self.slots) - 1}\x00"

    def render(self, text: str) -> str:
        # Cada paso solo si el texto trae su marca: casi todas las líneas son texto llano (rendimiento)
        if "`" in text:
            text = _CODE.sub(lambda m: self.keep(f"<code>{_esc(_code_text(m.group(2)))}</code>"), text)
        if "<!--" in text:
            text = _COMMENT.sub("", text)     # los comentarios HTML no se ven (como en GitHub)
        if "\n" in text:
            text = _HARD_BREAK.sub(lambda m: self.keep("<br>\n"), text)
        if "\\" in text:
            text = _ESCAPE.sub(lambda m: self.keep(_esc(m.group(1))), text)
        if "<" in text:
            text = _AUTOLINK.sub(lambda m: self._autolink(m.group(1)), text)
        if "[" in text:
            text = self._links(text)
        if "://" in text:
            text = _BARE_URL.sub(lambda m: self._autolink(m.group(1)), text)
        text = _esc(text)
        if "*" in text or "_" in text:
            for _ in range(3):  # anidados (***a***, **_a_**…)
                before = text
                text = _STRONG.sub(r"<strong>\2</strong>", text)
                text = _EM_STAR.sub(r"<em>\1</em>", text)
                text = _EM_UNDER.sub(r"<em>\1</em>", text)
                if text == before:
                    break
        if "~~" in text:
            text = _DEL.sub(r"<del>\1</del>", text)
        while "\x00" in text:
            new = re.sub(r"\x00(\d+)\x00", lambda m: self.slots[int(m.group(1))], text)
            if new == text:
                break
            text = new
        return text

    def _autolink(self, target: str) -> str:
        url = target if "://" in target or target.startswith("mailto:") else "mailto:" + target
        return self._anchor(url, _esc(target), "")

    def _anchor(self, url: str, inner: str, title: str) -> str:
        href = self.s.href(url)
        if href is None:
            return self.keep(inner)
        t = f' title="{_esc(title)}"' if title else ""
        return self.keep(f'<a href="{_esc(href)}"{t} rel="noopener noreferrer">{inner}</a>')

    def _image(self, url: str, alt: str, title: str) -> str:
        src = self.s.image(url.strip())
        if src is None:
            shown = _esc(url.strip())
            label = _esc(_("External image not loaded:"))
            opener = ""
            if re.match(r"https?://", url.strip()):
                opener = f' · <a href="{_esc(url.strip())}" rel="noopener noreferrer">{_esc(_("open the link"))}</a>'
            return self.keep(f'<span class="md-blocked">{label} <span class="md-blocked-url">{shown}</span>'
                             f"{opener}</span>")
        t = f' title="{_esc(title)}"' if title else ""
        return self.keep(f'<img src="{_esc(src)}" alt="{_esc(alt)}"{t} loading="lazy">')

    def _links(self, text: str) -> str:
        """``[texto](dirección "título")``, ``![alt](…)``, ``[texto][ref]``, ``[texto][]`` y ``[ref]``."""
        out, i, n = [], 0, len(text)
        while i < n:
            nxt = text.find("[", i)            # salta de corchete en corchete, no de carácter en carácter
            if nxt < 0:
                out.append(text[i:])
                break
            if nxt > 0 and text[nxt - 1] == "!" and nxt - 1 >= i:
                nxt -= 1
            if nxt > i:
                out.append(text[i:nxt])
                i = nxt
            is_image = text.startswith("![", i)
            if text[i] != "[" and not is_image:
                out.append(text[i])
                i += 1
                continue
            open_at = i + 1 if is_image else i
            close = _matching_bracket(text, open_at)
            if close < 0:
                out.append(text[i])
                i += 1
                continue
            label = text[open_at + 1:close]
            target, end = _destination(text, close + 1)
            if target is None:
                ref, end = _reference(text, close + 1, label)
                target = self.s.refs.get(ref) if ref else None
            if target is None:
                out.append(text[i])
                i += 1
                continue
            url, title = target
            if is_image:
                out.append(self._image(url, _plain(_Inline(self.s, self.slots).render(label)), title))
            else:
                out.append(self._anchor(url, _Inline(self.s, self.slots).render(label), title))
            i = end
        return "".join(out)


def _code_text(content: str) -> str:
    content = content.replace("\n", " ")
    if len(content) > 2 and content[0] == " " and content[-1] == " " and content.strip():
        return content[1:-1]
    return content


def _matching_bracket(text: str, start: int) -> int:
    depth, i = 0, start
    while i < len(text) and i - start < 2000:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_DEST = re.compile(r"\(\s*(<[^>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)(?:\s+(\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")


def _destination(text: str, at: int) -> tuple[tuple[str, str] | None, int]:
    m = _DEST.match(text, at)
    if not m:
        return None, at
    url = m.group(1)
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]
    title = (m.group(2) or "")[1:-1]
    return (html.unescape(url), title), m.end()


def _reference(text: str, at: int, label: str) -> tuple[str | None, int]:
    m = re.match(r"\[([^\]]*)\]", text[at:])
    if m:
        return (m.group(1) or label).strip().lower(), at + m.end()
    return label.strip().lower(), at

"""Markdown seguro (core/markdown.py) y lo que decide el visor (core/preview.py)."""
from __future__ import annotations

import io
import re

import pytest

from storageweb.core import markdown as md
from storageweb.core import preview


def _html(text: str, **kw) -> str:
    return md.render(text, **kw).html


def _links(url: str) -> str | None:
    if url.startswith(("http://", "https://", "mailto:")):
        return url
    return None if ":" in url.split("/")[0] else "/view/home/" + url


# --------------------------------------------------------------------------- seguridad

@pytest.mark.parametrize("attack", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">x</a>',
    "<iframe src=//evil></iframe>",
    "<svg onload=alert(1)>",
    "<style>body{display:none}</style>",
    "| a |\n|---|\n| <script>alert(1)</script> |",
    "> <img src=x onerror=alert(1)>",
    "- <b onclick=alert(1)>x</b>",
    "# <script>alert(1)</script>",
    "`<script>` y ```\n<script>alert(1)</script>\n```",
])
def test_raw_html_is_always_text(attack):
    out = _html(attack)
    for tag in ("<script", "<img", "<iframe", "<svg", "<style", "<b ", "<a "):
        assert tag not in out, (tag, out)
    assert "&lt;" in out


@pytest.mark.parametrize("url", ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>",
                                 "vbscript:x", "  javascript:alert(1)"])
def test_dangerous_links_lose_the_link(url):
    out = _html(f"[pulsa]({url}) y <{url}>", link=_links)
    assert "href=" not in out and "pulsa" in out


def test_attribute_injection_is_escaped():
    out = _html('[x](a.md "t\\" onmouseover=alert(1) x=") ![y" onerror="alert(1)](f.png)',
                link=_links, image=lambda u: "/download/home/" + u)
    assert 'onmouseover=alert' not in re.sub(r'title="[^"]*"', "", out)
    assert 'onerror="alert' not in out and 'alt="y&quot; onerror=&quot;alert(1)"' in out


def test_images_only_where_the_viewer_says():
    out = _html("![local](foto.png) ![fuera](https://tracker.example/p.gif)",
                image=lambda u: None if "://" in u else "/download/home/" + u)
    assert '<img src="/download/home/foto.png" alt="local"' in out
    assert "tracker.example/p.gif" in out and 'src="https://tracker' not in out and "md-blocked" in out


def test_depth_limit_does_not_recurse_forever():
    out = _html(">" * 5000 + " hondo")
    assert out.count("<blockquote>") <= md.MAX_DEPTH + 1 and "hondo" in out


# --------------------------------------------------------------------------- formato

def test_blocks_and_inline():
    out = _html("# Título\n\nTexto *a* **b** _c_ ~~d~~ `e<f>` snake_case_var.\n\n"
                "- uno\n- dos\n  - anidado\n- [x] hecho\n\n3. tres\n4. cuatro\n\n"
                "| A | B |\n|:-:|--:|\n| 1 | 2 \\| 3 |\n\n```py\nprint('<x>')\n```\n\n---\n\nSetext\n===\n"
                "\nsalto  \nforzado <!-- oculto -->")
    assert '<h1 id="h-titulo">Título</h1>' in out
    assert "<em>a</em>" in out and "<strong>b</strong>" in out and "<em>c</em>" in out and "<del>d</del>" in out
    assert "<code>e&lt;f&gt;</code>" in out and "snake_case_var" in out
    assert "<li>uno</li>" in out and "<ul>\n<li>anidado</li>\n</ul>" in out
    assert '<li class="task"><input type="checkbox" disabled checked> hecho</li>' in out
    assert '<ol start="3">' in out and "<li>cuatro</li>" in out
    assert '<th class="al-center">A</th>' in out and '<td class="al-right">2 | 3</td>' in out
    assert '<pre><code class="language-py">print(&#x27;&lt;x&gt;&#x27;)</code></pre>' in out
    assert "<hr>" in out and '<h1 id="h-setext">Setext</h1>' in out
    assert "salto<br>" in out and "oculto" not in out


def test_links_references_and_toc():
    r = md.render("## Calendario\n\n### Detalle\n\n## Calendario\n\n[ver](#Calendario) [doc][d] [d] "
                  "https://ejemplo.com/a. <ana@ejemplo.com>\n\n[d]: otra.md \"Otra\"", link=_links)
    assert r.toc == [(2, "Calendario", "h-calendario"), (3, "Detalle", "h-detalle"), (2, "Calendario", "h-calendario-1")]
    assert '<a href="#h-calendario" rel="noopener noreferrer">ver</a>' in r.html
    assert '<a href="/view/home/otra.md" title="Otra" rel="noopener noreferrer">doc</a>' in r.html
    assert '<a href="https://ejemplo.com/a" rel="noopener noreferrer">https://ejemplo.com/a</a>.' in r.html
    assert 'href="mailto:ana@ejemplo.com"' in r.html
    assert "[d]:" not in r.html


def test_without_resolvers_links_are_text():
    assert _html("[a](https://x.com)") == "<p>a</p>"


# --------------------------------------------------------------------------- visor

def test_secrets_are_blocked_by_default():
    """De serie no se abren los archivos de texto que suelen guardar secretos; .env cuenta como «env»."""
    for name in ("x.env", ".env", ".ENV", "server.pem", "id.key", "putty.ppk", "clave.asc"):
        assert preview.kind_of(name) is None, name
    assert preview.kind_of(".gitignore") == "text" and preview.kind_of("README") == "text"
    assert preview.kind_of(".env", {"enabled": True, "extensions": ["txt"], "blocked_extensions": []}) is None  # no listada


def test_kind_of_with_settings():
    options = {"enabled": True, "extensions": ["dat", "md", "txt", "env"], "blocked_extensions": ["env"]}
    assert preview.kind_of("a.dat", options) == "text" and preview.kind_of("a.dat") is None
    assert preview.kind_of("a.md", options) == "markdown" and preview.kind_of("x.env", options) is None  # bloqueada
    assert preview.kind_of("a.py", options) is None                                  # no está en la lista
    assert preview.kind_of("README", options) == "text"                              # por su nombre, siempre
    assert preview.kind_of("a.txt", {**options, "enabled": False}) is None


@pytest.mark.parametrize("name,kind", [("a.md", "markdown"), ("A.MARKDOWN", "markdown"), ("x.log", "text"),
                                       ("app.py", "text"), ("README", "text"), (".gitignore", "text"),
                                       ("p.html", "markup"), ("i.svg", "markup"), ("f.pdf", None), ("b.bin", None)])
def test_kind_of(name, kind):
    assert preview.kind_of(name) == kind


class _Backend:
    def __init__(self, data: bytes):
        self.data = data

    def local_path(self, rel):
        return None

    def open(self, rel):
        return io.BytesIO(self.data), len(self.data), 0


def test_read_text_encodings_binary_and_size():
    assert preview.read_text(_Backend("añ\r\nb\n".encode()), "a", 6).text == "añ\nb"
    latin = preview.read_text(_Backend("año".encode("cp1252")), "a", 3)
    assert latin.text == "año" and latin.encoding == "cp1252"
    assert preview.read_text(_Backend(b"ab\x00cd"), "a", 5).reason == "binary"
    assert preview.read_text(_Backend(b"x"), "a", preview.MAX_BYTES + 1).reason == "too_large"
    assert preview.read_text(_Backend(b"x" * 11), "a", 1, limit=10).reason == "too_large"  # tamaño que mentía


def test_resolve_stays_inside_the_root():
    assert preview.resolve("docs/guia.md", "img/a.png") == "docs/img/a.png"
    assert preview.resolve("docs/guia.md", "../otra.md#x") == "otra.md"
    assert preview.resolve("docs/guia.md", "/raiz.md") == "raiz.md"
    assert preview.resolve("docs/guia.md", "../../fuera.md") is None
    assert preview.resolve("guia.md", "") is None


def test_log_levels_and_neighbours():
    assert preview.log_level("2026 ERROR mal") == "error" and preview.log_level("[warn] x") == "warn"
    assert preview.log_level("errores sin nivel") == ""
    assert preview.log_level("Copia terminada: 1 aviso, 1 error") == ""   # la palabra, no el nivel
    assert preview.log_level("ts=1 level=warning msg=x") == "warn"
    entries = [{"name": n, "rel": f"d/{n}", "is_dir": n == "sub"} for n in ("sub", "a.md", "b.pdf", "c.txt", "d.log")]
    prev, nxt = preview.neighbours(entries, "d/c.txt")
    assert prev["name"] == "a.md" and nxt["name"] == "d.log"
    assert preview.neighbours(entries, "d/a.md")[0] is None


def test_code_inside_link_text():
    """Un enlace con código en su texto (``[`config.json`](…)``): el código ya está apartado cuando se convierte
    el texto del enlace (fallaba con IndexError y el visor daba error)."""
    out = _html("Ver [`config.json`](configuracion.md) y ![`alt`](a.png) en `x` [**negrita `y`**](b.md)",
                link=_links, image=lambda u: "/download/home/" + u)
    assert '<a href="/view/home/configuracion.md" rel="noopener noreferrer"><code>config.json</code></a>' in out
    assert 'alt="alt"' in out and "<code>x</code>" in out
    assert "<strong>negrita <code>y</code></strong></a>" in out


def test_mermaid_blocks_are_marked_for_the_viewer():
    r = md.render("```mermaid\nflowchart LR\n  A[<b>x</b>] --> B\n```\n\n```python\nx = 1\n```")
    assert r.diagrams == 1
    assert '<div class="md-diagram"><pre><code class="language-mermaid">flowchart LR\n  A[&lt;b&gt;x&lt;/b&gt;] --&gt; B' in r.html
    assert '<pre><code class="language-python">x = 1</code></pre>' in r.html and r.html.count("md-diagram") == 1


def test_vendored_libraries_match_their_hashes():
    """static/vendor/ (Mermaid) es lo que descargó tools/vendor.py con la huella fijada: nada cambiado a mano."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("vendor", Path(__file__).resolve().parents[2] / "tools" / "vendor.py")
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    assert vendor.check() == []

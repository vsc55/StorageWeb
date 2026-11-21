"""Visor de archivos (/view/…): Markdown renderizado o su código, texto con números de línea, HTML y SVG como
código, límites, permisos, carpetas ocultas, auditoría y enlaces desde el explorador."""
from __future__ import annotations

from storageweb.db.repositories import audit
from storageweb.web.context import get_db

from tests.helpers import add_user, login, visible


def _files(home):
    docs = home / "docs"
    docs.mkdir(parents=True)
    (docs / "guia.md").write_text(
        "# Guía\n\n## Instalar\n\nVer [la otra](otra.md#Pasos), [fuera](../../../../etc/passwd), "
        "[malo](javascript:alert(1)) y [web](https://ejemplo.com).\n\n"
        "![esquema](esquema.png) ![rastreo](https://tracker.example/p.gif)\n\n"
        "<script>alert('x')</script>\n", encoding="utf-8")
    (docs / "otra.md").write_text("## Pasos\n", encoding="utf-8")
    (docs / "esquema.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (docs / "app.log").write_text("2026 INFO ok\n2026 WARN cuidado\n2026 ERROR mal\n", encoding="utf-8")
    (docs / "pagina.html").write_text("<script>alert('x')</script>\n", encoding="utf-8")
    (docs / "datos.bin").write_bytes(b"\x00\x01\x02\x03")
    (docs / "latin.txt").write_bytes("año".encode("cp1252"))
    (docs / "falso.txt").write_bytes(bytes([0, 1]) + b"binario")
    return docs


def test_markdown_rendered_and_source(app, logged, home):
    client, _ = logged
    _files(home)
    page = client.get("/view/home/docs/guia.md")
    assert page.status_code == 200
    html = visible(page.get_data(as_text=True))
    assert '<h2 id="h-instalar">Instalar</h2>' in html
    assert "&lt;script&gt;alert" in html and "<script>alert" not in html          # el HTML del documento es texto
    assert 'href="/view/home/docs/otra.md#h-pasos"' in html                       # otro .md, al visor
    assert "passwd" not in html                                                   # fuera de la raíz: solo el texto
    assert 'href="javascript' not in html and 'href="https://ejemplo.com"' in html
    assert '<img src="/download/home/docs/esquema.png" alt="esquema"' in html
    assert 'src="https://tracker.example' not in html and "md-blocked" in html     # imágenes de fuera, no
    assert "En este documento" in html and 'href="#h-instalar"' in html
    assert 'class="segment active" href="/view/home/docs/guia.md"' in html
    source = visible(client.get("/view/home/docs/guia.md?source=1").get_data(as_text=True))
    assert 'id="viewer-text"' in source and "&lt;script&gt;alert" in source and "<h2" not in source


def test_text_log_markup_binary_and_encoding(app, logged, home):
    client, _ = logged
    _files(home)
    log = client.get("/view/home/docs/app.log").get_data(as_text=True)
    assert '<li class="lvl-warn">2026 WARN cuidado</li>' in log and '<li class="lvl-error">2026 ERROR mal</li>' in log
    assert "3 líneas" in log and "Ajustar líneas" in log
    markup = client.get("/view/home/docs/pagina.html").get_data(as_text=True)
    assert "Se muestra su código, no la página" in markup and "<script>alert" not in visible(markup)
    binary = client.get("/view/home/docs/falso.txt").get_data(as_text=True)    # .txt pero binario por dentro
    assert "no es un archivo de texto" in binary.lower() and 'id="viewer-text"' not in binary
    unknown = client.get("/view/home/docs/datos.bin")                            # fuera de la lista: se descarga
    assert unknown.status_code == 302 and unknown.location.endswith("/download/home/docs/datos.bin")
    latin = client.get("/view/home/docs/latin.txt").get_data(as_text=True)
    assert "<li>año</li>" in latin and "Windows-1252" in latin


def test_too_large(app, logged, home):
    client, _ = logged
    docs = _files(home)
    (docs / "grande.md").write_text("x" * (2 * 1024 * 1024 + 10), encoding="utf-8")
    page = client.get("/view/home/docs/grande.md").get_data(as_text=True)
    assert "demasiado grande" in page and "más de 2 MB" in page and 'id="viewer-text"' not in page


def test_previous_next_and_audit(app, logged, home):
    client, _ = logged
    _files(home)
    page = client.get("/view/home/docs/latin.txt").get_data(as_text=True)
    # Solo los que se ven, por nombre: app.log, esquema.png, falso.txt, guia.md, latin.txt, otra.md… (no .bin)
    assert 'href="/view/home/docs/guia.md"' in page and 'href="/view/home/docs/otra.md"' in page
    with app.app_context():
        row = audit.recent(get_db(), 1, action="download")[0]
    assert row["target"] == "home:/docs/latin.txt" and row["detail"] == "view"


def test_permissions_hidden_and_folders(app, make_app, client, home):
    app = make_app({"permissions": {"user": {"download": False}}, "storage": {"hidden": ["secreto.md"]}})
    add_user(app, "ana")
    c = app.test_client()
    login(c, "ana")
    docs = _files(home)
    (docs / "secreto.md").write_text("x", encoding="utf-8")
    assert c.get("/view/home/docs/guia.md").status_code == 403                    # el permiso de descargar
    other = make_app({"storage": {"hidden": ["secreto.md"]}})
    c2 = other.test_client()
    add_user(other, "luis")
    login(c2, "luis")
    luis = home.parent / "luis"
    (luis / "d").mkdir(parents=True)
    (luis / "d" / "secreto.md").write_text("x", encoding="utf-8")
    assert c2.get("/view/home/d/secreto.md").status_code == 404                   # oculto: como si no existiera
    assert c2.get("/view/home/d").status_code == 404                              # una carpeta no se «ve»
    assert c2.get("/view/home/../ana/docs/guia.md").status_code == 404


def test_browser_links_to_the_viewer(app, logged, home):
    client, _ = logged
    _files(home)
    page = client.get("/f/home/docs/").get_data(as_text=True)
    assert 'data-href="/view/home/docs/guia.md"' in page and 'data-view="/view/home/docs/guia.md"' in page
    assert 'data-download="/download/home/docs/guia.md"' in page
    assert 'data-href="/download/home/docs/datos.bin"' in page and 'data-view=""' in page   # no se ve: se descarga
    found = client.get("/search?q=guia").get_data(as_text=True)
    assert 'href="/view/home/docs/guia.md"' in found


def test_diagrams_are_drawn_in_an_isolated_frame(app, logged, home):
    client, _ = logged
    docs = _files(home)
    (docs / "flujo.md").write_text("# Flujo\n\n```mermaid\nflowchart LR\n  A --> B\n```\n", encoding="utf-8")
    page = client.get("/view/home/docs/flujo.md").get_data(as_text=True)
    assert 'data-diagram-frame="/diagram-frame"' in page and 'class="md-diagram"' in page
    assert "data-diagram-frame" not in client.get("/view/home/docs/otra.md").get_data(as_text=True)

    frame = app.test_client().get("/diagram-frame?dark=1")        # sin sesión: no lleva datos
    assert frame.status_code == 200
    csp = frame.headers["Content-Security-Policy"]
    assert csp.startswith("sandbox allow-scripts;") and "allow-same-origin" not in csp   # origen opaco
    assert "script-src 'self' http://localhost" in csp and "connect-src 'none'" in csp
    assert "frame-ancestors 'self' http://localhost" in csp and frame.headers["X-Frame-Options"] == "SAMEORIGIN"
    body = frame.get_data(as_text=True)
    assert "/static/vendor/mermaid/mermaid.min.js" in body and 'content="dark"' in body


def test_preview_settings(make_app, home):
    """preview.*: desactivar el visor, los diagramas, extensiones de más o excluidas y el tamaño máximo."""
    app = make_app({"preview": {"enabled": False}})
    add_user(app, "ana")
    c = app.test_client()
    login(c, "ana")
    docs = _files(home)
    resp = c.get("/view/home/docs/guia.md")                       # sin visor: a la descarga
    assert resp.status_code == 302 and resp.location.endswith("/download/home/docs/guia.md")
    assert 'data-href="/download/home/docs/guia.md"' in c.get("/f/home/docs/").get_data(as_text=True)

    from storageweb.settings.defaults import PREVIEW_EXTENSIONS
    app = make_app({"preview": {"diagrams": False, "extensions": [*PREVIEW_EXTENSIONS, "dat"],
                                "blocked_extensions": [".LOG"], "max_mb": 1}})
    c = app.test_client()
    login(c, "ana")
    (docs / "flujo.md").write_text("```mermaid\nflowchart LR\n  A --> B\n```\n", encoding="utf-8")
    (docs / "medidas.dat").write_text("1 2 3", encoding="utf-8")
    page = c.get("/view/home/docs/flujo.md").get_data(as_text=True)
    assert "data-diagram-frame" not in page and "language-mermaid" in page   # el código, sin Mermaid
    assert c.get("/diagram-frame").status_code == 404
    assert "<li>1 2 3</li>" in c.get("/view/home/docs/medidas.dat").get_data(as_text=True)
    assert c.get("/view/home/docs/app.log").status_code == 302              # excluida: se descarga
    listing = c.get("/f/home/docs/").get_data(as_text=True)
    assert 'data-href="/download/home/docs/app.log"' in listing and 'data-view="/view/home/docs/medidas.dat"' in listing
    (docs / "mediano.txt").write_text("y" * (1024 * 1024 + 5), encoding="utf-8")
    assert "Archivo grande" in c.get("/view/home/docs/mediano.txt").get_data(as_text=True)   # por partes


def test_preview_settings_page(app, admin):
    client, token = admin
    page = client.get("/admin/settings/preview").get_data(as_text=True)
    assert 'name="preview_diagrams"' in page and 'name="preview_blocked_extensions"' in page
    assert 'name="preview_extensions" rows="5" class="mono" data-list' in page and "markdown, md" in page
    client.post("/admin/settings/preview", data={"_csrf": token, "preview_enabled": "on", "preview_max_mb": "5",
                                                 "preview_extensions": "md, txt\ndat .OUT",
                                                 "preview_blocked_extensions": "env"})
    from tests.helpers import stored_settings
    stored = stored_settings(app)["preview"]
    assert stored["diagrams"] is False and stored["max_mb"] == 5
    assert stored["extensions"] == ["dat", "md", "out", "txt"] and stored["blocked_extensions"] == ["env"]
    bad = client.post("/admin/settings/preview", data={"_csrf": token, "preview_enabled": "on", "preview_max_mb": "50"})
    assert "preview.max_mb no puede ser más de 20" in bad.get_data(as_text=True)
    bad = client.post("/admin/settings/preview", data={"_csrf": token, "preview_enabled": "on", "preview_max_mb": "2",
                                                       "preview_extensions": "md, a/b"})
    assert "a/b no es una extensión de archivo" in bad.get_data(as_text=True)


def test_large_text_is_shown_by_parts(make_app, home):
    """Un texto más grande que preview.max_mb se ve por trozos (de entrada, el final) con líneas enteras."""
    app = make_app({"preview": {"max_mb": 1}})
    add_user(app, "ana")
    c = app.test_client()
    login(c, "ana")
    docs = home / "docs"
    docs.mkdir(parents=True)
    lines = [f"2026-11-20 linea {i:06d} INFO todo bien" for i in range(60000)]   # ~2,2 MB
    (docs / "grande.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tail = c.get("/view/home/docs/grande.log").get_data(as_text=True)
    assert "linea 059999" in tail and "linea 000000" not in tail and "Archivo grande" in tail
    assert 'class="code-lines no-numbers"' in tail and "?from=0" in tail
    head = c.get("/view/home/docs/grande.log?from=0").get_data(as_text=True)
    assert "<li>2026-11-20 linea 000000 INFO todo bien</li>" in head and "linea 059999" not in head
    middle = c.get("/view/home/docs/grande.log?from=1000001").get_data(as_text=True)
    first = middle.split('id="viewer-text">', 1)[1].split("</li>", 1)[0]
    assert first.startswith("<li>2026-11-20 linea ")                               # empieza en una línea entera
    (docs / "grande.md").write_text("x" * (1024 * 1024 + 10), encoding="utf-8")
    assert "demasiado grande" in c.get("/view/home/docs/grande.md").get_data(as_text=True)   # el Markdown, no


def test_code_colors(make_app, home):
    """preview.highlight: el código lleva su lenguaje y la página carga highlight.js (con el lenguaje extra si hace
    falta); los logs, los archivos grandes y el ajuste desactivado, sin colores."""
    app = make_app()
    add_user(app, "ana")
    c = app.test_client()
    login(c, "ana")
    home.mkdir(parents=True, exist_ok=True)
    (home / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (home / "deploy.ps1").write_text("Get-Item .\n", encoding="utf-8")
    (home / "Dockerfile").write_text("FROM python:3\n", encoding="utf-8")
    (home / "app.log").write_text("2026 ERROR mal\n", encoding="utf-8")
    (home / "notas.txt").write_text("hola\n", encoding="utf-8")
    (home / "guia.md").write_text("# G\n\n```python\nx = 1\n```\n", encoding="utf-8")
    (home / "grande.py").write_text("x = 1\n" * 200_000, encoding="utf-8")          # ~1,2 MB
    page = c.get("/view/home/app.py").get_data(as_text=True)
    assert 'data-lang="python"' in page and "vendor/highlight/highlight.min.js" in page
    assert "languages/powershell.min.js" not in page
    page = c.get("/view/home/deploy.ps1").get_data(as_text=True)
    assert 'data-lang="powershell"' in page and "languages/powershell.min.js" in page
    assert 'data-lang="dockerfile"' in c.get("/view/home/Dockerfile").get_data(as_text=True)
    for name in ("app.log", "notas.txt"):
        page = c.get(f"/view/home/{name}").get_data(as_text=True)
        assert "data-lang" not in page and "highlight.min.js" not in page
    md = c.get("/view/home/guia.md").get_data(as_text=True)
    assert 'class="language-python"' in md and "highlight.min.js" in md
    assert 'data-lang="markdown"' in c.get("/view/home/guia.md?source=1").get_data(as_text=True)
    assert "data-lang" not in c.get("/view/home/grande.py").get_data(as_text=True)
    off = make_app({"preview": {"highlight": False}})
    c2 = off.test_client()
    login(c2, "ana")
    page = c2.get("/view/home/app.py").get_data(as_text=True)
    assert "data-lang" not in page and "highlight.min.js" not in page

"""Visor de imágenes, PDF, vídeo y audio (/view/… y el contenido en /inline/…): qué se abre, con qué tipo y
cabeceras se sirve (nunca como página), rangos, auditoría, permisos, ocultos y los ajustes de cada tipo."""
from __future__ import annotations

from storageweb.db.repositories import audit
from storageweb.web.context import get_db

from tests.helpers import login, stored_settings, signed_in

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")


def _files(home):
    media = home / "media"
    media.mkdir(parents=True)
    (media / "foto.png").write_bytes(PNG)
    (media / "informe.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    (media / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40)
    (media / "tema.mp3").write_bytes(b"ID3" + bytes(200))
    (media / "dibujo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                                      encoding="utf-8")
    (media / "pagina.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    # Un HTML disfrazado de imagen: se sirve como image/png (lo dice la extensión, no el contenido) y con nosniff
    (media / "trampa.png").write_text("<html><script>alert(1)</script></html>", encoding="utf-8")
    return media


def test_each_kind_opens_in_its_element(app, logged, home):
    client, _ = logged
    _files(home)
    image = client.get("/view/home/media/foto.png").get_data(as_text=True)
    assert '<img src="/inline/home/media/foto.png" alt="foto.png">' in image and "Imagen · PNG" in image
    assert 'id="viewer-media-error" hidden' in image and 'href="/download/home/media/foto.png"' in image
    pdf = client.get("/view/home/media/informe.pdf").get_data(as_text=True)
    assert '<iframe class="viewer-pdf" src="/inline/home/media/informe.pdf"' in pdf
    video = client.get("/view/home/media/clip.mp4").get_data(as_text=True)
    assert '<video controls preload="metadata" src="/inline/home/media/clip.mp4">' in video and "Vídeo · MP4" in video
    audio = client.get("/view/home/media/tema.mp3").get_data(as_text=True)
    assert '<audio controls preload="metadata" src="/inline/home/media/tema.mp3">' in audio
    # El SVG y el HTML siguen viéndose como código
    svg = client.get("/view/home/media/dibujo.svg").get_data(as_text=True)
    assert 'id="viewer-text"' in svg and "/inline/" not in svg


def test_inline_serves_the_type_of_the_table_never_as_a_page(app, logged, home):
    client, _ = logged
    _files(home)
    image = client.get("/inline/home/media/foto.png")
    assert image.status_code == 200 and image.data == PNG
    assert image.headers["Content-Type"] == "image/png" and image.headers["X-Content-Type-Options"] == "nosniff"
    assert image.headers["Content-Security-Policy"] == "sandbox"
    assert image.headers["Content-Disposition"].startswith("inline")
    assert image.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert image.headers["X-Frame-Options"] == "DENY"
    trap = client.get("/inline/home/media/trampa.png")             # HTML dentro: sigue siendo una imagen
    assert trap.headers["Content-Type"] == "image/png" and trap.headers["Content-Security-Policy"] == "sandbox"
    pdf = client.get("/inline/home/media/informe.pdf")
    assert pdf.headers["Content-Type"] == "application/pdf"
    # Aislado como lo demás, y solo enmarcable desde aquí (el visor lo pone en un marco)
    assert pdf.headers["Content-Security-Policy"] == "sandbox; default-src 'none'; frame-ancestors 'self'"
    assert pdf.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert client.get("/inline/home/media/clip.mp4").headers["Content-Type"] == "video/mp4"
    assert client.get("/inline/home/media/tema.mp3").headers["Content-Type"] == "audio/mpeg"
    # Lo que no es multimedia no se sirve en línea: se descarga como adjunto
    for name in ("dibujo.svg", "pagina.html"):
        assert client.get(f"/inline/home/media/{name}").status_code == 404
    assert client.get("/inline/home/media").status_code == 404
    assert client.get("/inline/home/media/no-existe.png").status_code == 404


def test_ranges_and_one_audit_entry_per_view(app, logged, home):
    client, _ = logged
    media = _files(home)
    size = (media / "clip.mp4").stat().st_size
    with app.app_context():
        before = len(audit.recent(get_db(), 100, action="download"))
    first = client.get("/inline/home/media/clip.mp4", headers={"Range": "bytes=0-"})
    assert first.status_code == 206 and first.headers["Content-Range"] == f"bytes 0-{size - 1}/{size}"
    seek = client.get("/inline/home/media/clip.mp4", headers={"Range": "bytes=5000-5099"})
    assert seek.status_code == 206 and len(seek.data) == 100
    with app.app_context():
        rows = audit.recent(get_db(), 100, action="download")
    assert len(rows) == before + 1                                 # saltar en el vídeo no es otra descarga
    assert rows[0]["target"] == "home:/media/clip.mp4" and rows[0]["detail"] == "view"
    client.get("/view/home/media/clip.mp4")                        # la página no lo cuenta: no lleva el contenido
    with app.app_context():
        assert len(audit.recent(get_db(), 100, action="download")) == before + 1


def test_previous_and_next_include_media(app, logged, home):
    client, _ = logged
    _files(home)
    page = client.get("/view/home/media/foto.png").get_data(as_text=True)
    # Por nombre: clip.mp4, dibujo.svg, foto.png, informe.pdf…
    assert 'href="/view/home/media/dibujo.svg"' in page and 'href="/view/home/media/informe.pdf"' in page


def test_permissions_and_hidden(make_app, home):
    app = make_app({"permissions": {"user": {"download": False}}, "storage": {"hidden": ["*.mp3"]}})
    c, _ = signed_in(app, "ana", csrf_url=None)
    _files(home)
    assert c.get("/inline/home/media/foto.png").status_code == 403
    assert c.get("/view/home/media/foto.png").status_code == 403
    assert app.test_client().get("/inline/home/media/foto.png").status_code == 302      # sin sesión: a entrar
    other = make_app({"storage": {"hidden": ["*.mp3"]}})
    c2, _ = signed_in(other, "luis", csrf_url=None)
    luis = home.parent / "luis"
    luis.mkdir(parents=True, exist_ok=True)
    (luis / "oculto.mp3").write_bytes(b"ID3")
    assert c2.get("/inline/home/oculto.mp3").status_code == 404
    assert c2.get("/inline/home/../ana/media/foto.png").status_code == 404


def test_each_kind_can_be_turned_off(make_app, home):
    app = make_app({"preview": {"images": False, "pdf": False, "video": False, "audio": False}})
    c, _ = signed_in(app, "ana", csrf_url=None)
    _files(home)
    for name in ("foto.png", "informe.pdf", "clip.mp4", "tema.mp3"):
        view = c.get(f"/view/home/media/{name}")
        assert view.status_code == 302 and view.location.endswith(f"/download/home/media/{name}")
        assert c.get(f"/inline/home/media/{name}").status_code == 404
    listing = c.get("/f/home/media/").get_data(as_text=True)
    assert 'data-href="/download/home/media/foto.png"' in listing
    # Las bloqueadas ganan también aquí
    blocked = make_app({"preview": {"blocked_extensions": ["pdf"]}})
    c = blocked.test_client()
    login(c, "ana")
    assert c.get("/inline/home/media/informe.pdf").status_code == 404
    assert c.get("/view/home/media/foto.png").status_code == 200


def test_settings_page_saves_each_kind(app, admin):
    client, token = admin
    page = client.get("/admin/settings/preview").get_data(as_text=True)
    for key in ("images", "pdf", "video", "audio"):
        assert f'name="preview_{key}" checked' in page
    client.post("/admin/settings/preview", data={"_csrf": token, "preview_thumbnail_max_mb": "30", "preview_thumbnail_cache_mb": "500", "preview_enabled": "on", "preview_max_mb": "2",
                                                 "preview_images": "on", "preview_audio": "on",
                                                 "preview_extensions": "md, txt", "preview_blocked_extensions": ""})
    stored = stored_settings(app)["preview"]
    assert stored["pdf"] is False and stored["video"] is False
    assert "images" not in stored and "audio" not in stored          # de serie: no se guardan


def test_they_are_never_edited(make_app, home):
    app = make_app({"permissions": {"user": {"edit": True}}})
    c, _ = signed_in(app, "ana", csrf_url=None)
    _files(home)
    resp = c.get("/edit/home/media/foto.png")                       # con permiso de editar: vuelve al visor
    assert resp.status_code == 302 and resp.location.endswith("/view/home/media/foto.png")
    assert "/edit/" not in c.get("/view/home/media/foto.png").get_data(as_text=True)

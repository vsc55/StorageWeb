"""Miniaturas de las imágenes en el explorador (preview.thumbnails, core/thumbnails.py, files.thumbnail)."""
from __future__ import annotations

import io
import os
import time

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from storageweb.core import thumbnails  # noqa: E402
from tests.helpers import update_settings  # noqa: E402


def _png(path, size=(800, 600), color=(30, 120, 200), mode="RGB"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path, "PNG")
    return path


def test_only_images_the_viewer_opens():
    on = {"enabled": True, "images": True, "thumbnails": True, "extensions": [], "blocked_extensions": []}
    assert thumbnails.can_thumb("foto.JPG", on) and thumbnails.can_thumb("logo.png", on)
    assert not thumbnails.can_thumb("dibujo.svg", on) and not thumbnails.can_thumb("doc.pdf", on)
    assert not thumbnails.can_thumb("foto.jpg", {**on, "thumbnails": False})
    assert not thumbnails.can_thumb("foto.jpg", {**on, "images": False})       # sin imágenes en el visor, tampoco
    assert not thumbnails.can_thumb("foto.jpg", {**on, "enabled": False})
    assert set(thumbnails.formats()) >= {"png", "jpg", "jpeg", "gif", "webp"}


def test_the_route_makes_and_keeps_them(app, logged, home):
    client, _token = logged
    _png(home / "foto.png")
    (home / "notas.txt").write_text("hola", encoding="utf-8")
    page = client.get("/f/home/").get_data(as_text=True)
    assert 'data-thumb="/thumb/home/foto.png?v=' in page and "notas.txt" in page
    assert page.count("data-thumb=") == 1                                     # el texto, no
    resp = client.get("/thumb/home/foto.png")
    assert resp.status_code == 200 and resp.mimetype == thumbnails.mimetype()
    assert "sandbox" in resp.headers["Content-Security-Policy"] and "private" in resp.headers["Cache-Control"]
    with Image.open(io.BytesIO(resp.data)) as img:
        assert max(img.size) == thumbnails.SIZE and img.size == (256, 192)
    with app.app_context():
        from storageweb.web.context import settings
        cache = thumbnails.cache_dir(settings()["data_dir"])
    stored = list(cache.glob("*/*"))
    assert len(stored) == 1 and str(home) not in str(stored[0])               # aparte, nunca en su carpeta
    assert client.get("/thumb/home/foto.png").status_code == 200 and len(list(cache.glob("*/*"))) == 1
    # El archivo cambia: otra miniatura (otra clave)
    time.sleep(1.1)
    _png(home / "foto.png", size=(300, 900))
    with Image.open(io.BytesIO(client.get("/thumb/home/foto.png").data)) as img:
        assert img.size == (85, 256)
    assert client.get("/thumb/home/notas.txt").status_code == 404
    assert client.get("/thumb/home/no-existe.png").status_code == 404
    assert client.get("/thumb/home/../../secreto.png").status_code == 404


def test_broken_disguised_or_too_large(app, logged, home):
    client, _token = logged
    (home).mkdir(parents=True, exist_ok=True)
    (home / "roto.png").write_bytes(b"\x89PNG\r\n\x1a\nesto no es una imagen")
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40)).save(buffer, "JPEG")
    (home / "disfrazada.png").write_bytes(buffer.getvalue())                  # un JPEG con nombre de PNG
    Image.frombytes("RGB", (1000, 1000), os.urandom(3_000_000)).save(home / "grande.png", "PNG")   # ruido: ~3 MB
    assert (home / "grande.png").stat().st_size > 1024 * 1024
    assert client.get("/thumb/home/roto.png").status_code == 404
    assert client.get("/thumb/home/disfrazada.png").status_code == 404       # solo se prueba el formato de su extensión
    update_settings(app, preview={"thumbnail_max_mb": 1})
    assert client.get("/thumb/home/grande.png").status_code == 404
    update_settings(app, preview={"thumbnail_max_mb": 30})
    assert client.get("/thumb/home/grande.png").status_code == 200
    old = thumbnails.MAX_PIXELS
    thumbnails.MAX_PIXELS = 100 * 100                                        # una «bomba»: más píxeles de la cuenta
    try:
        _png(home / "bomba.png", size=(200, 200))
        assert client.get("/thumb/home/bomba.png").status_code == 404
    finally:
        thumbnails.MAX_PIXELS = old


def test_permissions_and_the_setting(app, logged, home):
    client, _token = logged
    _png(home / "foto.png")
    update_settings(app, preview={"thumbnails": False})
    assert client.get("/thumb/home/foto.png").status_code == 404
    assert "data-thumb=" not in client.get("/f/home/").get_data(as_text=True)
    update_settings(app, preview={"thumbnails": True}, permissions={"user": {"download": False}})
    assert client.get("/thumb/home/foto.png").status_code == 403
    assert "data-thumb=" not in client.get("/f/home/").get_data(as_text=True)


def test_transparency_is_kept(app, logged, home):
    client, _token = logged
    _png(home / "logo.png", size=(64, 64), color=(0, 0, 0, 0), mode="RGBA")
    with Image.open(io.BytesIO(client.get("/thumb/home/logo.png").data)) as img:
        assert img.mode in ("RGBA", "LA") and img.getpixel((0, 0))[-1] == 0


def test_cleanup(tmp_path):
    base = thumbnails.cache_dir(tmp_path)
    (base / "aa").mkdir(parents=True)
    old, new = base / "aa" / "viejo.webp", base / "aa" / "nuevo.webp"
    old.write_bytes(b"x" * 10)
    new.write_bytes(b"x" * 10)
    past = time.time() - 90 * 86400
    os.utime(old, (past, past))
    assert thumbnails.cleanup(tmp_path, max_mb=100) == 1 and new.exists() and not old.exists()
    for i in range(5):
        f = base / "aa" / f"{i}.webp"
        f.write_bytes(b"x" * 400_000)
        os.utime(f, (time.time() - 1000 + i, time.time() - 1000 + i))
    assert thumbnails.cleanup(tmp_path, max_mb=1) >= 3                     # pasan de 1 MB: fuera las menos usadas
    assert thumbnails.usage(tmp_path)["bytes"] <= 1024 * 1024

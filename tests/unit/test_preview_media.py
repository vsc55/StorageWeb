"""Tipos de imagen, PDF, vídeo y audio del visor (core/media_types.json): qué abre cada uno, y que el archivo de datos
no pueda colar un tipo que ejecute código ni un ajuste que no existe."""
from __future__ import annotations

import json

import pytest

from storageweb.core import preview
from storageweb.settings import DEFAULTS


def test_kinds_and_types():
    assert preview.kind_of("Foto.JPG") == "image" and preview.mime_of("Foto.JPG") == "image/jpeg"
    assert preview.kind_of("informe.pdf") == "pdf" and preview.kind_of("clip.webm") == "video"
    assert preview.kind_of("tema.flac") == "audio" and preview.mime_of("tema.mp3") == "audio/mpeg"
    assert preview.kind_of("dibujo.svg") == "markup" and preview.mime_of("dibujo.svg") == ""   # el SVG, como código
    assert preview.kind_of("video.mkv") is None                                                  # no está: se descarga


def test_each_kind_follows_its_setting_and_the_blocked_list():
    off = {**DEFAULTS["preview"], "images": False}
    assert preview.kind_of("a.png", off) is None and preview.kind_of("a.pdf", off) == "pdf"
    assert preview.kind_of("a.pdf", {**DEFAULTS["preview"], "blocked_extensions": ["pdf"]}) is None
    assert preview.kind_of("a.png", {**DEFAULTS["preview"], "enabled": False}) is None


def test_the_shipped_file_names_real_settings():
    assert set(preview.MEDIA_SETTINGS) == {"image", "pdf", "video", "audio"}
    assert all(isinstance(DEFAULTS["preview"][s], bool) for s in preview.MEDIA_SETTINGS.values())


@pytest.mark.parametrize("bad", [
    {"image": {"setting": "images", "types": {"svg": "image/svg+xml"}}},          # ejecuta código
    {"image": {"setting": "images", "types": {"htm": "text/html"}}},             # una página
    {"image": {"setting": "images", "types": {"png": "text/plain"}}},            # no es multimedia
    {"image": {"setting": "nope", "types": {"png": "image/png"}}},               # el ajuste no existe
    {"image": {"setting": "max_mb", "types": {"png": "image/png"}}},             # no es un interruptor
    {"text": {"setting": "images", "types": {"png": "image/png"}}},              # un tipo de texto
    {"image": {"setting": "images", "types": {"png": "image/png"}},
     "video": {"setting": "video", "types": {"png": "video/mp4"}}},               # la misma extensión dos veces
    {"image": {"setting": "images", "types": {"p/ng": "image/png"}}},            # no es una extensión
])
def test_a_wrong_data_file_stops_the_start(tmp_path, bad):
    path = tmp_path / "media_types.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        preview.load_media(path)

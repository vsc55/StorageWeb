"""Marca: logo propio, imagen del inicio de sesión y color principal.

Cada imagen se guarda en ``<data_dir>/brand/<nombre>.<ext>`` (``logo.png``, ``login.jpg``…) y su nombre
en su ajuste (``branding.logo``, ``branding.login_image``).
El color se sirve como hoja de estilo (``/brand.css``) porque la CSP no permite estilos en línea.
Un SVG se sirve con ``Content-Security-Policy: sandbox`` para que no pueda ejecutar código aunque
se abra directamente.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path

from ..i18n import _, _l
from ..settings.defaults import LOGIN_ART_CHOICES, LOGIN_ARTS

# Nombre de cada opción de la ilustración del inicio de sesión, en el orden de LOGIN_ART_CHOICES
LOGIN_ART_LABELS = dict(zip(LOGIN_ART_CHOICES, (_l("Classic"), _l("Sync"), _l("Waves"), _l("File mosaic"),
                                                _l("Storage layers"), _l("Random"))))


def pick_login_art(choice: str) -> str:
    """La ilustración que se muestra: la elegida o, con «random», una al azar en cada carga."""
    return random.choice(LOGIN_ARTS) if choice == "random" else choice

TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".svg": "image/svg+xml"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_COLOR = "#2563eb"  # el --primary de serie (base.css)


@dataclass(frozen=True)
class Image:
    key: str          # clave del ajuste en «branding»
    stem: str         # nombre del fichero sin extensión
    max_bytes: int

    @property
    def name_re(self) -> re.Pattern:
        return re.compile(rf"^{self.stem}\.(png|jpg|jpeg|webp|svg)$")


IMAGES = {
    "logo": Image("logo", "logo", 512 * 1024),
    "login_image": Image("login_image", "login", 3 * 1024 * 1024),
}


class BrandingError(Exception):
    pass


def brand_dir(cfg: dict) -> Path:
    return Path(cfg["data_dir"]) / "brand"


def _looks_like(ext: str, data: bytes) -> bool:
    head = data[:512]
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".svg":
        text = data[:4096].decode("utf-8", "ignore").lower()
        return "<svg" in text
    return False


def save_image(cfg: dict, kind: str, filename: str, data: bytes) -> str:
    """Guarda la imagen ``kind`` (``logo``/``login_image``) y devuelve su nombre (``logo.png``…)."""
    image = IMAGES[kind]
    ext = Path(filename or "").suffix.lower()
    if ext not in TYPES:
        raise BrandingError(_("The image must be a PNG, JPEG, WebP or SVG file."))
    if not data or len(data) > image.max_bytes:
        raise BrandingError(_("The image must be at most %(kb)s KB.", kb=image.max_bytes // 1024))
    if not _looks_like(ext, data):
        raise BrandingError(_("The file is not a valid %(type)s image.", type=ext[1:].upper()))
    folder = brand_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    name = image.stem + (".jpg" if ext == ".jpeg" else ext)
    tmp = folder / (name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(folder / name)
    for other in folder.glob(f"{image.stem}.*"):
        if other.name != name:
            other.unlink(missing_ok=True)
    return name


def remove_image(cfg: dict, kind: str) -> None:
    for path in brand_dir(cfg).glob(f"{IMAGES[kind].stem}.*"):
        path.unlink(missing_ok=True)


def image_path(cfg: dict, kind: str) -> Path | None:
    name = cfg["branding"][kind]
    if not name or not IMAGES[kind].name_re.match(name):
        return None
    path = brand_dir(cfg) / name
    return path if path.is_file() else None


def favicon_svg(cfg: dict) -> str:
    """Icono de la pestaña sin logo propio: el cubo de serie sobre el color principal."""
    color = cfg["branding"]["primary_color"] or DEFAULT_COLOR
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            f'<rect width="32" height="32" rx="8" fill="{color}"/>'
            '<g fill="#fff" transform="translate(4 4)">'
            '<path d="M12 2.8 20 7.3 12 11.8 4 7.3z"/>'
            '<path fill-opacity=".7" d="M4 8.4l7.4 4.2v8.6L4 17z"/>'
            '<path fill-opacity=".45" d="M20 8.4l-7.4 4.2v8.6L20 17z"/></g></svg>')


def stylesheet(cfg: dict) -> str:
    color = cfg["branding"]["primary_color"]
    if not color:
        return "/* sin color propio */\n"
    # El color propio para el tema claro y el oscuro; los tonos suaves salen de él
    return (":root, [data-theme] {\n"
            f"  --primary: {color};\n"
            f"  --primary-soft: color-mix(in srgb, {color} 14%, var(--bg));\n"
            f"  --primary-ink: color-mix(in srgb, {color} 70%, var(--fg));\n"
            "}\n"
            f".rail-brand, .brand-mark {{ background: {color}; }}\n")

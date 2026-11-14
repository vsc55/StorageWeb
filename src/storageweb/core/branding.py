"""Marca: logo propio y color principal.

El logo se guarda en ``<data_dir>/brand/logo.<ext>`` y su nombre en el ajuste ``branding.logo``.
El color se sirve como hoja de estilo (``/brand.css``) porque la CSP no permite estilos en línea.
Un SVG se sirve con ``Content-Security-Policy: sandbox`` para que no pueda ejecutar código aunque
se abra directamente.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..i18n import _

MAX_BYTES = 512 * 1024
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".svg": "image/svg+xml"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGO_RE = re.compile(r"^logo\.(png|jpg|jpeg|webp|svg)$")


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


def save_logo(cfg: dict, filename: str, data: bytes) -> str:
    """Guarda el logo y devuelve el nombre con el que queda (``logo.png``…)."""
    ext = Path(filename or "").suffix.lower()
    if ext not in TYPES:
        raise BrandingError(_("The logo must be a PNG, JPEG, WebP or SVG image."))
    if not data or len(data) > MAX_BYTES:
        raise BrandingError(_("The logo must be at most %(kb)s KB.", kb=MAX_BYTES // 1024))
    if not _looks_like(ext, data):
        raise BrandingError(_("The file is not a valid %(type)s image.", type=ext[1:].upper()))
    folder = brand_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    name = "logo" + (".jpg" if ext == ".jpeg" else ext)
    tmp = folder / (name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(folder / name)
    for other in folder.glob("logo.*"):
        if other.name != name:
            other.unlink(missing_ok=True)
    return name


def remove_logo(cfg: dict) -> None:
    for path in brand_dir(cfg).glob("logo.*"):
        path.unlink(missing_ok=True)


def logo_path(cfg: dict) -> Path | None:
    name = cfg["branding"]["logo"]
    if not name or not LOGO_RE.match(name):
        return None
    path = brand_dir(cfg) / name
    return path if path.is_file() else None


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

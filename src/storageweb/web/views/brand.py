"""Marca: hoja de estilo con el color propio y las imágenes (públicas: las usa también el login)."""
from __future__ import annotations

from flask import Blueprint, Response, abort, send_file

from ...core import branding
from ..context import settings

bp = Blueprint("brand", __name__)


@bp.route("/brand.css")
def stylesheet():
    resp = Response(branding.stylesheet(settings()), mimetype="text/css")
    resp.headers["Cache-Control"] = "public, max-age=3600"  # la URL lleva la versión
    return resp


@bp.route("/brand/favicon.svg")
def favicon():
    resp = Response(branding.favicon_svg(settings()), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "public, max-age=3600"  # la URL lleva la versión
    return resp


def _send(kind: str):
    path = branding.image_path(settings(), kind)
    if path is None:
        abort(404)
    resp = send_file(path, mimetype=branding.TYPES[path.suffix], max_age=3600)
    if path.suffix == ".svg":
        # Un SVG puede llevar scripts: abierto directamente no debe poder ejecutarlos
        resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp


@bp.route("/brand/logo")
def logo():
    return _send("logo")


@bp.route("/brand/login-image")
def login_image():
    return _send("login_image")

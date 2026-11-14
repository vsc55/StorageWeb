"""Marca: hoja de estilo con el color propio y el logo (públicos: los usa también el login)."""
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


@bp.route("/brand/logo")
def logo():
    cfg = settings()
    path = branding.logo_path(cfg)
    if path is None:
        abort(404)
    resp = send_file(path, mimetype=branding.TYPES[path.suffix], max_age=3600)
    if path.suffix == ".svg":
        # Un SVG puede llevar scripts: abierto directamente no debe poder ejecutarlos
        resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp

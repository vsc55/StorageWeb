"""El selector de rutas de los campos de la administración (*Examinar* y autocompletado, ``admin/path-picker.js``):
el contenido de una carpeta en JSON. A qué mira lo dice el campo (``scope``); lo resuelve ``core/pathpicker``."""
from __future__ import annotations

import hmac

from flask import abort, jsonify, request, session

from ....core import pathpicker, storage
from ....db.repositories import users
from ...context import get_db, settings
from ...guards import admin_required
from . import bp


@bp.route("/browse")
@admin_required
def browse():
    """``scope=root`` (``user`` = uid, ``root`` = su carpeta; carpetas y archivos), ``scope=location`` (``location``;
    sin ella, el disco del servidor: ``scope=disk``, con ``start`` como punto de partida) y ``path``."""
    # Una petición GET, pero que recorre carpetas y se conecta a ubicaciones: solo desde el JavaScript de la propia
    # página (lleva el token CSRF en la cabecera). Si no, otra web podría hacer que el navegador de un administrador
    # navegara aquí (la cookie va con SameSite=Lax) y provocar ese trabajo, aunque no pudiera leer la respuesta
    sent, expected = request.headers.get("X-CSRF-Token", ""), session.get("_csrf", "")
    if not expected or not hmac.compare_digest(sent.encode(), str(expected).encode()):
        abort(403)
    cfg = settings()
    scope = request.args.get("scope", "")
    path = request.args.get("path", "")[:4096]
    if scope == "root":
        user = users.get_by_uid(get_db(), request.args.get("user", ""))
        if user is None:
            abort(404)
        root = next((r for r in storage.available_roots(user, cfg) if r["name"] == request.args.get("root")), None)
        if root is None:
            abort(404)
        return jsonify(pathpicker.browse_root(cfg, root, path, files=request.args.get("files") == "1"))
    if scope == "location" and request.args.get("location"):
        return jsonify(pathpicker.browse_location(cfg, request.args["location"], path))
    if scope in ("location", "disk"):
        return jsonify(pathpicker.browse_disk(path, request.args.get("start", "")[:4096],
                                              allowed=cfg["storage"]["allowed_folders"]))
    abort(400)

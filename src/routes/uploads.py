"""API JSON de subidas por partes (la usa web/static/js/app.js).

    POST   /api/uploads                {root, path, name, size}  -> 201 {id, chunk_size, received}
    GET    /api/uploads/<id>                                     -> {id, name, size, received, chunk_size}
    PUT    /api/uploads/<id>?offset=N  cuerpo binario (una parte) -> {received}
    POST   /api/uploads/<id>/complete                            -> {name, size}
    DELETE /api/uploads/<id>                                     -> 204
"""
from __future__ import annotations

import secrets
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request

from ..config import settings
from ..core import storage
from ..core import uploads as core
from ..core.permissions import effective_for_root, permissions_for
from ..core.security import PathError, resolve_inside, safe_filename
from ..db import audit
from ..db import uploads as repo
from .guards import client_ip

bp = Blueprint("uploads", __name__, url_prefix="/api/uploads")


class _Abort(Exception):
    def __init__(self, message: str, status: int, **extra):
        self.message, self.status, self.extra = message, status, extra


@bp.errorhandler(_Abort)
def _abort_handler(exc: _Abort):
    return jsonify(error=exc.message, **exc.extra), exc.status


@bp.errorhandler(core.UploadError)
def _upload_error(exc: core.UploadError):
    return jsonify(error=exc.message, **exc.extra), exc.status


@bp.before_request
def _require_login():
    if g.get("user") is None:
        raise _Abort("Sesión no iniciada", 401)


def _chunk_size() -> int:
    return core.chunk_size(current_app.config["SW"]["server"]["max_upload_mb"])


def _writable_dir(root_name: str, rel: str) -> tuple[dict, Path]:
    """Comprueba (cada vez) que el usuario sigue teniendo acceso y permiso de subida."""
    cfg = settings.current()
    try:
        root = storage.find_root(g.user, cfg, root_name)
        directory = resolve_inside(root["path"], rel)
    except (storage.RootNotFound, PathError):
        raise _Abort("Carpeta no encontrada", 404) from None
    if not directory.is_dir():
        raise _Abort("Carpeta no encontrada", 404)
    if "upload" not in effective_for_root(permissions_for(g.user, cfg), root):
        raise _Abort("No tienes permiso para subir archivos aquí", 403)
    return root, directory


def _load(upload_id: str):
    row = repo.get(upload_id)
    if row is None or row["user_id"] != g.user["id"]:
        raise _Abort("Subida no encontrada", 404)
    root, directory = _writable_dir(row["root"], row["dir_rel"])
    return row, root, directory, core.part_path(directory, upload_id)


def _cleanup_stale() -> None:
    for row in repo.stale(core.STALE_HOURS):
        core.discard(core.part_path(Path(row["dir_path"]), row["id"]))
        repo.delete(row["id"])


@bp.route("", methods=["POST"])
def init():
    data = request.get_json(silent=True) or {}
    root, directory = _writable_dir(str(data.get("root", "")), str(data.get("path", "")))
    try:
        filename = safe_filename(str(data.get("name", "")))
    except ValueError as exc:
        raise _Abort(str(exc), 400) from None
    size = core.validate_size(data.get("size"), settings.current()["storage"]["max_file_size_mb"])
    core.check_space(directory, size)
    _cleanup_stale()

    upload_id = secrets.token_hex(16)
    core.part_path(directory, upload_id).touch(exist_ok=False)
    repo.create(upload_id=upload_id, user_id=g.user["id"], root=root["name"],
                dir_rel=storage.rel_path(root, directory), dir_path=str(directory),
                filename=filename, size=size)
    return jsonify(id=upload_id, chunk_size=_chunk_size(), received=0), 201


@bp.route("/<upload_id>", methods=["GET"])
def status(upload_id: str):
    row, _, _, part = _load(upload_id)
    return jsonify(id=row["id"], name=row["filename"], size=row["size"],
                   received=core.received(part), chunk_size=_chunk_size())


@bp.route("/<upload_id>", methods=["PUT"])
def put_chunk(upload_id: str):
    row, _, _, part = _load(upload_id)
    try:
        offset = int(request.args.get("offset", ""))
    except ValueError:
        raise _Abort("Falta el parámetro offset", 400) from None
    new_size = core.append(part, request.stream, offset, row["size"])
    repo.touch(upload_id)
    return jsonify(received=new_size)


@bp.route("/<upload_id>/complete", methods=["POST"])
def complete(upload_id: str):
    row, root, directory, part = _load(upload_id)
    final = core.finalize(part, directory, row["filename"], row["size"])
    repo.delete(upload_id)
    audit.log("upload", f"{root['name']}:/{storage.rel_path(root, final)}", username=g.user["username"],
              ip=client_ip(), detail=str(row["size"]))
    return jsonify(name=final.name, size=row["size"])


@bp.route("/<upload_id>", methods=["DELETE"])
def cancel(upload_id: str):
    row = repo.get(upload_id)
    if row is None or row["user_id"] != g.user["id"]:
        raise _Abort("Subida no encontrada", 404)
    core.discard(core.part_path(Path(row["dir_path"]), upload_id))
    repo.delete(upload_id)
    return "", 204

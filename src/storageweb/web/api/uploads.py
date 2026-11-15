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

from flask import Blueprint, abort, g, request

from ...core import backends, storage
from ...core import uploads as core
from ...core import quota, tokens
from ...core.permissions import effective_for_root, permissions_for
from ...core.security import PathError, safe_filename
from ...db.repositories import audit
from ...db.repositories import uploads as repo
from ...i18n import _
from ..context import boot_config, get_db, settings
from ..guards import client_ip
from . import json_api

bp = Blueprint("uploads", __name__, url_prefix="/api/uploads")
json_api(bp)


@bp.errorhandler(core.UploadError)
def _upload_error(exc: core.UploadError):
    return {"error": exc.message, **exc.extra}, exc.status


@bp.before_request
def _require_login():
    if g.get("user") is None:
        abort(401, description=_("Not signed in"))


def _chunk_size() -> int:
    return core.chunk_size(boot_config()["server"]["max_upload_mb"])


def _writable_dir(root_name: str, rel: str) -> tuple[dict, str]:
    """Comprueba (en cada petición) que el usuario sigue teniendo acceso y permiso de subida."""
    cfg = settings()
    try:
        root = storage.find_root(g.user, cfg, root_name)
        dir_rel = backends.clean_rel(rel)
        if storage.is_hidden(cfg, dir_rel):
            raise PathError(dir_rel)
        is_dir = root["backend"].is_dir(dir_rel)
    except (storage.RootNotFound, PathError):
        abort(404, description=_("Folder not found"))
    except backends.BackendError as exc:
        abort(502, description=exc.message)
    if not is_dir:
        abort(404, description=_("Folder not found"))
    if "upload" not in tokens.restrict(effective_for_root(permissions_for(g.user, cfg), root), g.get("api_token")):
        abort(403, description=_("You are not allowed to upload files here"))
    return root, dir_rel


def _owned(upload_id: str):
    row = repo.get(get_db(), upload_id)
    if row is None or row["user_id"] != g.user["id"]:
        abort(404, description=_("Upload not found"))
    return row


def _load(upload_id: str):
    row = _owned(upload_id)
    root, dir_rel = _writable_dir(row["root"], row["dir_rel"])
    return row, root, dir_rel, core.part_path(Path(row["dir_path"]), upload_id)


def _cleanup_stale() -> None:
    conn = get_db()
    for row in repo.stale(conn, core.STALE_HOURS):
        core.discard(core.part_path(Path(row["dir_path"]), row["id"]))
        repo.delete(conn, row["id"])


@bp.route("", methods=["POST"])
def init():
    data = request.get_json(silent=True) or {}
    root, dir_rel = _writable_dir(str(data.get("root", "")), str(data.get("path", "")))
    try:
        filename = safe_filename(str(data.get("name", "")))
        storage.check_visible_name(settings(), backends.join_rel(dir_rel, filename))
    except ValueError as exc:
        abort(400, description=str(exc))
    size = core.validate_size(data.get("size"), settings()["storage"]["max_file_size_mb"])
    core.check_space(root["backend"], dir_rel, size)
    _cleanup_stale()

    upload_id = secrets.token_hex(16)
    staging = root["backend"].staging_dir(dir_rel)  # junto al destino si es local; si no, <data_dir>/uploads
    core.part_path(staging, upload_id).touch(exist_ok=False)
    repo.create(get_db(), upload_id=upload_id, user_id=g.user["id"], root=root["name"],
                dir_rel=dir_rel, dir_path=str(staging), filename=filename, size=size)
    return {"id": upload_id, "chunk_size": _chunk_size(), "received": 0}, 201


@bp.route("/<upload_id>", methods=["GET"])
def status(upload_id: str):
    row, _root, _dir, part = _load(upload_id)
    return {"id": row["id"], "name": row["filename"], "size": row["size"],
            "received": core.received(part), "chunk_size": _chunk_size()}


@bp.route("/<upload_id>", methods=["PUT"])
def put_chunk(upload_id: str):
    row, _root, _dir, part = _load(upload_id)
    try:
        offset = int(request.args.get("offset", ""))
    except ValueError:
        abort(400, description=_("The offset parameter is missing"))
    new_size = core.append(part, request.stream, offset, row["size"])
    repo.touch(get_db(), upload_id)
    return {"received": new_size}


@bp.route("/<upload_id>/complete", methods=["POST"])
def complete(upload_id: str):
    row, root, dir_rel, part = _load(upload_id)
    final = core.finalize(part, root["backend"], dir_rel, row["filename"], row["size"])
    quota.invalidate(root)
    repo.delete(get_db(), upload_id)
    audit.log(get_db(), "upload", f"{root['name']}:/{final}",
              username=g.user["username"], ip=client_ip(), detail=str(row["size"]))
    return {"name": backends.name_of(final), "size": row["size"]}


@bp.route("/<upload_id>", methods=["DELETE"])
def cancel(upload_id: str):
    row = _owned(upload_id)
    core.discard(core.part_path(Path(row["dir_path"]), upload_id))
    repo.delete(get_db(), upload_id)
    return "", 204

"""Explorador de archivos: listar, subir, descargar, crear carpetas, renombrar y borrar.

Las operaciones van al ``backend`` de cada raíz (disco local, S3 o SMB) con rutas relativas a ella.
"""
from __future__ import annotations

import mimetypes
import secrets
from datetime import datetime, timezone

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file,
                   url_for)

from ...core import backends, storage, tokens
from ...core.permissions import PERMISSION_LABELS, effective_for_root, permissions_for
from ...core.security import UPLOAD_TMP_PREFIX, PathError, safe_filename
from ...db.repositories import audit
from ...i18n import _, ngettext
from ..context import boot_config, get_db, settings
from ..guards import client_ip, login_required

bp = Blueprint("files", __name__)


def _root(name: str) -> dict:
    try:
        return storage.find_root(g.user, settings(), name)
    except storage.RootNotFound as exc:
        abort(404, description=str(exc) or None)


def _rel(sub: str) -> str:
    try:
        return backends.clean_rel(sub)
    except PathError:
        abort(404)


def _stat(root: dict, rel: str):
    try:
        return root["backend"].stat(rel)
    except backends.BackendError as exc:
        abort(502, description=exc.message)


def _perms(root: dict) -> frozenset[str]:
    return tokens.restrict(effective_for_root(permissions_for(g.user, settings()), root), g.get("api_token"))


def _require(root: dict, perm: str) -> None:
    if perm in _perms(root):
        return
    if root["read_only"] and perm != "download":
        abort(403, description=_("This folder is read-only."))
    abort(403, description=_("You are not allowed to: %(action)s.", action=str(PERMISSION_LABELS[perm]).lower()))


def _audit(action: str, root: dict, rel: str, detail: str | None = None) -> None:
    audit.log(get_db(), action, f"{root['name']}:/{rel}", username=g.user["username"], ip=client_ip(),
              detail=detail)


def _wants_json() -> bool:
    return request.headers.get("Accept", "").startswith("application/json")


def _back(root: dict, rel: str):
    return redirect(url_for("files.browse", root=root["name"], sub=rel))


def _require_dir(root: dict, rel: str) -> None:
    entry = _stat(root, rel)
    if entry is None or not entry.is_dir:
        abort(404)


@bp.route("/")
@login_required
def index():
    return redirect(url_for("files.browse", root="home", sub=""))


@bp.route("/f/<root>/", defaults={"sub": ""})
@bp.route("/f/<root>/<path:sub>")
@login_required
def browse(root, sub):
    r = _root(root)
    rel = _rel(sub)
    entry = _stat(r, rel)
    if entry is not None and not entry.is_dir:
        return redirect(url_for("files.download", root=root, sub=rel))
    if entry is None:
        abort(404)
    try:
        sort = request.args.get("sort", "name")
        sort = sort if sort in storage.SORT_KEYS else "name"
        descending = request.args.get("order") == "desc"
        entries = storage.list_directory(r, rel, settings()["storage"]["show_hidden"], sort, descending)
    except PermissionError:
        abort(403, description=_("The service is not allowed to read this folder."))
    except backends.BackendError as exc:
        abort(502, description=exc.message)
    if _wants_json() or g.get("api_token") is not None:
        return jsonify(root=r["name"], path=rel, permissions=sorted(_perms(r)), entries=[
            {"name": e["name"], "type": "dir" if e["is_dir"] else "file", "size": e["bytes"],
             "modified": datetime.fromtimestamp(e["ts"], timezone.utc).isoformat(timespec="seconds"),
             "path": e["rel"]} for e in entries])
    parent = "/".join(rel.split("/")[:-1]) if rel else None
    return render_template("browse.html", root=r, roots=storage.available_roots(g.user, settings()),
                           rel=rel, crumbs=storage.breadcrumbs(rel), parent=parent, entries=entries,
                           perms=_perms(r), max_upload_mb=boot_config()["server"]["max_upload_mb"],
                           sort=sort, descending=descending,
                           max_file_size_mb=settings()["storage"]["max_file_size_mb"])


def _stream(root: dict, rel: str, name: str):
    """Descarga desde S3 o SMB: el fichero remoto con ``seek`` sirve rangos (reanudar, vídeo)."""
    try:
        fh, size, mtime = root["backend"].open(rel)
    except FileNotFoundError:
        abort(404)
    except backends.BackendError as exc:
        abort(502, description=exc.message)
    rv = send_file(fh, as_attachment=True, download_name=name, conditional=False, max_age=0,
                   mimetype=mimetypes.guess_type(name)[0] or "application/octet-stream")
    rv.content_length = size  # send_file no sabe el tamaño de un fichero que no está en disco
    rv.last_modified = datetime.fromtimestamp(mtime, timezone.utc) if mtime else None
    rv.set_etag(f"{int(mtime)}-{size}")
    return rv.make_conditional(request.environ, accept_ranges=True, complete_length=size)


@bp.route("/download/<root>/<path:sub>")
@login_required
def download(root, sub):
    r = _root(root)
    _require(r, "download")
    rel = _rel(sub)
    entry = _stat(r, rel)
    if entry is None or entry.is_dir:
        abort(404)
    _audit("download", r, rel)
    local = r["backend"].local_path(rel)
    if local is not None:
        return send_file(local, as_attachment=True, download_name=local.name, conditional=True, max_age=0)
    return _stream(r, rel, entry.name)


@bp.route("/upload/<root>/", defaults={"sub": ""}, methods=["POST"])
@bp.route("/upload/<root>/<path:sub>", methods=["POST"])
@login_required
def upload(root, sub):
    r = _root(root)
    _require(r, "upload")
    rel = _rel(sub)
    _require_dir(r, rel)
    backend = r["backend"]

    saved, errors = [], []
    for item in request.files.getlist("files"):
        if not item or not item.filename:
            continue
        try:
            name = safe_filename(item.filename)
        except ValueError as exc:
            errors.append(f"{item.filename}: {exc}")
            continue
        tmp = backend.staging_dir(rel) / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
        try:
            item.save(tmp)
            size = tmp.stat().st_size
            final = backend.unique_rel(rel, name)
            backend.store(tmp, final)
        except (OSError, backends.BackendError) as exc:
            current_app.logger.exception("Error saving %s", name)
            errors.append(f"{name}: {_reason(exc) or _('write error')}")
            tmp.unlink(missing_ok=True)
            continue
        saved.append(backends.name_of(final))
        _audit("upload", r, final, detail=str(size))

    if _wants_json():
        return jsonify(saved=saved, errors=errors), (200 if saved or not errors else 400)
    if saved:
        flash(ngettext("%(num)d file uploaded.", "%(num)d files uploaded.", len(saved)), "info")
    for e in errors:
        flash(e, "error")
    return _back(r, rel)


def _reason(exc: Exception) -> str:
    if isinstance(exc, backends.BackendError):
        return exc.message
    return getattr(exc, "strerror", None) or str(exc)


@bp.route("/mkdir/<root>/", defaults={"sub": ""}, methods=["POST"])
@bp.route("/mkdir/<root>/<path:sub>", methods=["POST"])
@login_required
def mkdir(root, sub):
    r = _root(root)
    _require(r, "mkdir")
    rel = _rel(sub)
    _require_dir(r, rel)
    try:
        name = safe_filename(request.form.get("name", ""))
        new_rel = backends.join_rel(rel, name)
        r["backend"].mkdir(new_rel)
        _audit("mkdir", r, new_rel)
        flash(_("Folder «%(name)s» created.", name=name), "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash(_("An item with that name already exists."), "error")
    except (OSError, backends.BackendError) as exc:
        flash(_("Could not create the folder: %(error)s", error=_reason(exc)), "error")
    return _back(r, rel)


@bp.route("/rename/<root>/<path:sub>", methods=["POST"])
@login_required
def rename(root, sub):
    r = _root(root)
    _require(r, "rename")
    rel = _rel(sub)
    if not rel or _stat(r, rel) is None:
        abort(404)
    parent = backends.parent_rel(rel)
    try:
        new_name = safe_filename(request.form.get("name", ""))
        r["backend"].rename(rel, new_name)
        _audit("rename", r, rel, detail=new_name)
        flash(_("Renamed."), "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash(_("An item with that name already exists."), "error")
    except (OSError, backends.BackendError) as exc:
        flash(_("Could not rename: %(error)s", error=_reason(exc)), "error")
    return _back(r, parent)


@bp.route("/delete/<root>/<path:sub>", methods=["POST"])
@login_required
def delete(root, sub):
    r = _root(root)
    _require(r, "delete")
    rel = _rel(sub)
    if not rel:
        abort(404)
    if _stat(r, rel) is None and not _is_broken_link(r, rel):
        abort(404)
    parent = backends.parent_rel(rel)
    try:
        r["backend"].delete(rel)
        _audit("delete", r, rel)
        flash(_("«%(name)s» deleted.", name=backends.name_of(rel)), "info")
    except (OSError, backends.BackendError) as exc:
        flash(_("Could not delete: %(error)s", error=_reason(exc)), "error")
    return _back(r, parent)


def _is_broken_link(root: dict, rel: str) -> bool:
    """Un symlink roto en el disco local: no tiene ``stat`` pero se puede borrar."""
    local = root["backend"].local_path(backends.parent_rel(rel))
    return bool(local is not None and (local / backends.name_of(rel)).is_symlink())

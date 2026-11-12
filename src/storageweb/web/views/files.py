"""Explorador de archivos: listar, subir, descargar, crear carpetas, renombrar y borrar."""
from __future__ import annotations

import os
import secrets
import shutil

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, send_file, url_for)

from ...core import storage
from ...core.permissions import PERMISSION_LABELS, effective_for_root, permissions_for
from ...core.security import UPLOAD_TMP_PREFIX, resolve_entry, resolve_inside, safe_filename
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


def _perms(root: dict) -> frozenset[str]:
    return effective_for_root(permissions_for(g.user, settings()), root)


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


@bp.route("/")
@login_required
def index():
    return redirect(url_for("files.browse", root="home", sub=""))


@bp.route("/f/<root>/", defaults={"sub": ""})
@bp.route("/f/<root>/<path:sub>")
@login_required
def browse(root, sub):
    r = _root(root)
    target = resolve_inside(r["path"], sub)
    if target.is_file():
        return redirect(url_for("files.download", root=root, sub=sub))
    if not target.is_dir():
        abort(404)
    try:
        sort = request.args.get("sort", "name")
        sort = sort if sort in storage.SORT_KEYS else "name"
        descending = request.args.get("order") == "desc"
        entries = storage.list_directory(r, target, settings()["storage"]["show_hidden"], sort, descending)
    except PermissionError:
        abort(403, description=_("The service is not allowed to read this folder."))
    rel = storage.rel_path(r, target)
    parent = "/".join(rel.split("/")[:-1]) if rel else None
    return render_template("browse.html", root=r, roots=storage.available_roots(g.user, settings()),
                           rel=rel, crumbs=storage.breadcrumbs(rel), parent=parent, entries=entries,
                           perms=_perms(r), max_upload_mb=boot_config()["server"]["max_upload_mb"],
                           sort=sort, descending=descending,
                           max_file_size_mb=settings()["storage"]["max_file_size_mb"])


@bp.route("/download/<root>/<path:sub>")
@login_required
def download(root, sub):
    r = _root(root)
    _require(r, "download")
    target = resolve_inside(r["path"], sub)
    if not target.is_file():
        abort(404)
    _audit("download", r, storage.rel_path(r, target))
    return send_file(target, as_attachment=True, download_name=target.name, conditional=True, max_age=0)


@bp.route("/upload/<root>/", defaults={"sub": ""}, methods=["POST"])
@bp.route("/upload/<root>/<path:sub>", methods=["POST"])
@login_required
def upload(root, sub):
    r = _root(root)
    _require(r, "upload")
    directory = resolve_inside(r["path"], sub)
    if not directory.is_dir():
        abort(404)

    saved, errors = [], []
    for item in request.files.getlist("files"):
        if not item or not item.filename:
            continue
        try:
            name = safe_filename(item.filename)
        except ValueError as exc:
            errors.append(f"{item.filename}: {exc}")
            continue
        tmp = directory / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
        try:
            item.save(tmp)
            final = storage.unique_path(directory, name)
            os.replace(tmp, final)
        except OSError as exc:
            current_app.logger.exception("Error saving %s", name)
            errors.append(name + ": " + (exc.strerror or _("write error")))
            tmp.unlink(missing_ok=True)
            continue
        saved.append(final.name)
        _audit("upload", r, storage.rel_path(r, final), detail=str(final.stat().st_size))

    if _wants_json():
        return jsonify(saved=saved, errors=errors), (200 if saved or not errors else 400)
    if saved:
        flash(ngettext("%(num)d file uploaded.", "%(num)d files uploaded.", len(saved)), "info")
    for e in errors:
        flash(e, "error")
    return _back(r, storage.rel_path(r, directory))


@bp.route("/mkdir/<root>/", defaults={"sub": ""}, methods=["POST"])
@bp.route("/mkdir/<root>/<path:sub>", methods=["POST"])
@login_required
def mkdir(root, sub):
    r = _root(root)
    _require(r, "mkdir")
    directory = resolve_inside(r["path"], sub)
    if not directory.is_dir():
        abort(404)
    try:
        name = safe_filename(request.form.get("name", ""))
        new_dir = directory / name
        new_dir.mkdir()
        _audit("mkdir", r, storage.rel_path(r, new_dir))
        flash(_("Folder «%(name)s» created.", name=name), "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash(_("An item with that name already exists."), "error")
    except OSError as exc:
        flash(_("Could not create the folder: %(error)s", error=exc.strerror), "error")
    return _back(r, storage.rel_path(r, directory))


@bp.route("/rename/<root>/<path:sub>", methods=["POST"])
@login_required
def rename(root, sub):
    r = _root(root)
    _require(r, "rename")
    target = resolve_entry(r["path"], sub)
    parent_rel = storage.rel_path(r, target.parent)
    try:
        new_name = safe_filename(request.form.get("name", ""))
        dest = target.parent / new_name
        if dest.exists():
            raise FileExistsError
        old_rel = storage.rel_path(r, target)
        target.rename(dest)
        _audit("rename", r, old_rel, detail=new_name)
        flash(_("Renamed."), "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash(_("An item with that name already exists."), "error")
    except OSError as exc:
        flash(_("Could not rename: %(error)s", error=exc.strerror), "error")
    return _back(r, parent_rel)


@bp.route("/delete/<root>/<path:sub>", methods=["POST"])
@login_required
def delete(root, sub):
    r = _root(root)
    _require(r, "delete")
    target = resolve_entry(r["path"], sub)
    parent_rel = storage.rel_path(r, target.parent)
    rel = storage.rel_path(r, target)
    try:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        _audit("delete", r, rel)
        flash(_("«%(name)s» deleted.", name=target.name), "info")
    except OSError as exc:
        flash(_("Could not delete: %(error)s", error=exc.strerror), "error")
    return _back(r, parent_rel)

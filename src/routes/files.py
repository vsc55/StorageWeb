"""Explorador de archivos: listar, subir, descargar, crear carpetas, renombrar y borrar."""
from __future__ import annotations

import os
import secrets
import shutil

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, send_file, url_for)

from ..config import settings
from ..core import storage
from ..core.permissions import PERMISSION_LABELS, effective_for_root, permissions_for
from ..core.security import UPLOAD_TMP_PREFIX, resolve_entry, resolve_inside, safe_filename
from ..db import audit
from .guards import client_ip, login_required

bp = Blueprint("files", __name__)


def _root(name: str) -> dict:
    try:
        return storage.find_root(g.user, settings.current(), name)
    except storage.RootNotFound as exc:
        abort(404, description=str(exc) or None)


def _perms(root: dict) -> frozenset[str]:
    return effective_for_root(permissions_for(g.user, settings.current()), root)


def _require(root: dict, perm: str) -> None:
    if perm in _perms(root):
        return
    if root["read_only"] and perm != "download":
        abort(403, description="Esta carpeta es de solo lectura.")
    abort(403, description=f"No tienes permiso para: {PERMISSION_LABELS[perm].lower()}.")


def _audit(action: str, root: dict, rel: str, detail: str | None = None) -> None:
    audit.log(action, f"{root['name']}:/{rel}", username=g.user["username"], ip=client_ip(),
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
        entries = storage.list_directory(r, target, settings.current()["storage"]["show_hidden"])
    except PermissionError:
        abort(403, description="El servicio no tiene permisos para leer esta carpeta.")
    rel = storage.rel_path(r, target)
    parent = "/".join(rel.split("/")[:-1]) if rel else None
    return render_template("browse.html", root=r, roots=storage.available_roots(g.user, settings.current()),
                           rel=rel, crumbs=storage.breadcrumbs(rel), parent=parent, entries=entries,
                           perms=_perms(r), max_upload_mb=current_app.config["SW"]["server"]["max_upload_mb"],
                           max_file_size_mb=settings.current()["storage"]["max_file_size_mb"])


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
            current_app.logger.exception("Error guardando %s", name)
            errors.append(f"{name}: {exc.strerror or 'error de escritura'}")
            tmp.unlink(missing_ok=True)
            continue
        saved.append(final.name)
        _audit("upload", r, storage.rel_path(r, final), detail=str(final.stat().st_size))

    if _wants_json():
        return jsonify(saved=saved, errors=errors), (200 if saved or not errors else 400)
    if saved:
        flash(f"Subidos {len(saved)} archivo(s).", "info")
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
        flash(f"Carpeta «{name}» creada.", "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash("Ya existe un elemento con ese nombre.", "error")
    except OSError as exc:
        flash(f"No se pudo crear la carpeta: {exc.strerror}", "error")
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
        flash("Renombrado correctamente.", "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash("Ya existe un elemento con ese nombre.", "error")
    except OSError as exc:
        flash(f"No se pudo renombrar: {exc.strerror}", "error")
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
        flash(f"«{target.name}» eliminado.", "info")
    except OSError as exc:
        flash(f"No se pudo eliminar: {exc.strerror}", "error")
    return _back(r, parent_rel)

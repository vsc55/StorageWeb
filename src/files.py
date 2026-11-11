"""Explorador de archivos: listar, subir, descargar, crear carpetas y borrar."""
from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, send_file, url_for)

from . import db
from .security import (UPLOAD_TMP_PREFIX, login_required, resolve_inside, safe_filename,
                       safe_username_for_path)

bp = Blueprint("files", __name__)


# --------------------------------------------------------------------------- raíces

def _cfg() -> dict:
    return current_app.config["SW"]


def home_path_for(user) -> Path:
    if user["home_path"]:
        return Path(user["home_path"])
    tmpl = _cfg()["storage"]["home_template"]
    return Path(tmpl.replace("{username}", safe_username_for_path(user["username"])))


def available_roots(user) -> list[dict]:
    """Raíces accesibles para el usuario: su home + los shares permitidos."""
    roots = [{"name": "home", "label": "Mi carpeta", "path": home_path_for(user), "read_only": False}]
    uname = user["username"].lower()
    ugroups = db.user_groups(user)
    for share in _cfg()["storage"]["shares"]:
        if "*" in share["users"] or uname in share["users"] or ugroups.intersection(share["groups"]):
            roots.append({**share, "path": Path(share["path"])})
    return roots


def _get_root(name: str) -> dict:
    for root in available_roots(g.user):
        if root["name"] == name:
            path = root["path"]
            if not path.exists():
                if root["name"] == "home" and _cfg()["storage"]["create_home"]:
                    path.mkdir(parents=True, exist_ok=True)
                    try:
                        os.chmod(path, 0o750)
                    except OSError:
                        pass
                else:
                    abort(404, description="La carpeta configurada no existe en el servidor.")
            return root
    abort(404)


def _rel(root: dict, target: Path) -> str:
    rel = target.relative_to(root["path"].resolve())
    return "" if str(rel) == "." else rel.as_posix()


def _audit(action: str, root: dict, rel: str, detail: str | None = None) -> None:
    db.audit(action, f"{root['name']}:/{rel}", username=g.user["username"],
             ip=request.remote_addr, detail=detail)


def _resolve_entry(root: dict, sub: str) -> Path:
    """Como resolve_inside pero sin seguir el symlink del último elemento (para borrar/renombrar)."""
    parts = [p for p in sub.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or parts[-1] == "..":
        abort(404)
    parent = resolve_inside(root["path"], "/".join(parts[:-1]))
    entry = parent / parts[-1]
    if not (entry.exists() or entry.is_symlink()):
        abort(404)
    return entry


def _wants_json() -> bool:
    return request.headers.get("Accept", "").startswith("application/json")


def _require_writable(root: dict) -> None:
    if root["read_only"]:
        abort(403, description="Esta carpeta es de solo lectura.")


def _unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(1, 10000):
        candidate = directory / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    abort(409, description="Demasiados archivos con el mismo nombre.")


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


# --------------------------------------------------------------------------- vistas

@bp.route("/")
@login_required
def index():
    return redirect(url_for("files.browse", root="home", sub=""))


@bp.route("/f/<root>/", defaults={"sub": ""})
@bp.route("/f/<root>/<path:sub>")
@login_required
def browse(root, sub):
    r = _get_root(root)
    target = resolve_inside(r["path"], sub)
    if target.is_file():
        return redirect(url_for("files.download", root=root, sub=sub))
    if not target.is_dir():
        abort(404)

    show_hidden = _cfg()["storage"]["show_hidden"]
    entries = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                if entry.name.startswith(UPLOAD_TMP_PREFIX):
                    continue
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir()
                    st = entry.stat()
                except OSError:
                    continue
                entries.append({
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": "" if is_dir else _human_size(st.st_size),
                    "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "rel": (f"{_rel(r, target)}/{entry.name}").lstrip("/"),
                })
    except PermissionError:
        abort(403, description="El servicio no tiene permisos para leer esta carpeta.")
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

    rel = _rel(r, target)
    crumbs, acc = [], []
    for part in rel.split("/") if rel else []:
        acc.append(part)
        crumbs.append({"name": part, "rel": "/".join(acc)})
    parent = "/".join(rel.split("/")[:-1]) if rel else None

    return render_template("browse.html", root=r, roots=available_roots(g.user), rel=rel,
                           crumbs=crumbs, parent=parent, entries=entries,
                           max_upload_mb=_cfg()["server"]["max_upload_mb"])


@bp.route("/download/<root>/<path:sub>")
@login_required
def download(root, sub):
    r = _get_root(root)
    target = resolve_inside(r["path"], sub)
    if not target.is_file():
        abort(404)
    _audit("download", r, _rel(r, target))
    return send_file(target, as_attachment=True, download_name=target.name, conditional=True,
                     max_age=0)


@bp.route("/upload/<root>/", defaults={"sub": ""}, methods=["POST"])
@bp.route("/upload/<root>/<path:sub>", methods=["POST"])
@login_required
def upload(root, sub):
    r = _get_root(root)
    _require_writable(r)
    directory = resolve_inside(r["path"], sub)
    if not directory.is_dir():
        abort(404)

    saved, errors = [], []
    for storage in request.files.getlist("files"):
        if not storage or not storage.filename:
            continue
        try:
            name = safe_filename(storage.filename)
        except ValueError as exc:
            errors.append(f"{storage.filename}: {exc}")
            continue
        tmp = directory / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
        try:
            storage.save(tmp)
            final = _unique_path(directory, name)
            os.replace(tmp, final)
        except OSError as exc:
            current_app.logger.exception("Error guardando %s", name)
            errors.append(f"{name}: {exc.strerror or 'error de escritura'}")
            tmp.unlink(missing_ok=True)
            continue
        saved.append(final.name)
        _audit("upload", r, _rel(r, final), detail=str(final.stat().st_size))

    if _wants_json():
        return jsonify(saved=saved, errors=errors), (200 if saved or not errors else 400)
    if saved:
        flash(f"Subidos {len(saved)} archivo(s).", "info")
    for e in errors:
        flash(e, "error")
    return redirect(url_for("files.browse", root=root, sub=_rel(r, directory)))


@bp.route("/mkdir/<root>/", defaults={"sub": ""}, methods=["POST"])
@bp.route("/mkdir/<root>/<path:sub>", methods=["POST"])
@login_required
def mkdir(root, sub):
    r = _get_root(root)
    _require_writable(r)
    directory = resolve_inside(r["path"], sub)
    if not directory.is_dir():
        abort(404)
    try:
        name = safe_filename(request.form.get("name", ""))
        new_dir = directory / name
        new_dir.mkdir()
        _audit("mkdir", r, _rel(r, new_dir))
        flash(f"Carpeta «{name}» creada.", "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash("Ya existe un elemento con ese nombre.", "error")
    except OSError as exc:
        flash(f"No se pudo crear la carpeta: {exc.strerror}", "error")
    return redirect(url_for("files.browse", root=root, sub=_rel(r, directory)))


@bp.route("/rename/<root>/<path:sub>", methods=["POST"])
@login_required
def rename(root, sub):
    r = _get_root(root)
    _require_writable(r)
    target = _resolve_entry(r, sub)
    parent_rel = _rel(r, target.parent)
    try:
        new_name = safe_filename(request.form.get("name", ""))
        dest = target.parent / new_name
        if dest.exists():
            raise FileExistsError
        old_rel = _rel(r, target)
        target.rename(dest)
        _audit("rename", r, old_rel, detail=new_name)
        flash("Renombrado correctamente.", "info")
    except ValueError as exc:
        flash(str(exc), "error")
    except FileExistsError:
        flash("Ya existe un elemento con ese nombre.", "error")
    except OSError as exc:
        flash(f"No se pudo renombrar: {exc.strerror}", "error")
    return redirect(url_for("files.browse", root=root, sub=parent_rel))


@bp.route("/delete/<root>/<path:sub>", methods=["POST"])
@login_required
def delete(root, sub):
    r = _get_root(root)
    _require_writable(r)
    target = _resolve_entry(r, sub)
    parent_rel = _rel(r, target.parent)
    rel = _rel(r, target)
    try:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        _audit("delete", r, rel)
        flash(f"«{target.name}» eliminado.", "info")
    except OSError as exc:
        flash(f"No se pudo eliminar: {exc.strerror}", "error")
    return redirect(url_for("files.browse", root=root, sub=parent_rel))

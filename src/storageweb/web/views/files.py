"""Explorador de archivos: listar, subir, descargar, crear carpetas, renombrar y borrar.

Las operaciones van al ``backend`` de cada raíz (disco local, S3 o SMB) con rutas relativas a ella.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request,
                   stream_with_context, url_for)

from ... import patterns
from ...core import backends, storage, tokens
from ...core import files as files_core
from ...core import quota
from ...core.permissions import PERMISSION_LABELS, effective_for_root, permissions_for
from ...core.security import UPLOAD_TMP_PREFIX, PathError, safe_filename
from ...db.repositories import audit
from ...i18n import _, ngettext
from ..context import boot_config, get_db, settings
from ..downloads import SANDBOX, send_entry
from ..guards import client_ip, login_required, safe_next

bp = Blueprint("files", __name__)


def _root(name: str) -> dict:
    try:
        return storage.find_root(g.user, settings(), name)
    except storage.RootNotFound as exc:
        abort(404, description=str(exc) or None)


def _rel(sub: str) -> str:
    try:
        rel = backends.clean_rel(sub)
    except PathError:
        abort(404)
    if storage.is_hidden(settings(), rel):
        abort(404)  # oculto para todos (storage.hidden): como si no existiera
    return rel


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
        hidden = patterns.of(settings())
        entries = storage.list_directory(r, rel, settings()["storage"]["show_hidden"], sort, descending,
                                         hidden=hidden)
    except PermissionError:
        abort(403, description=_("The service is not allowed to read this folder."))
    except backends.BackendError as exc:
        abort(502, description=exc.message)
    if _wants_json() or g.get("api_token") is not None:
        space = storage.space_of(r, rel)
        q = quota.status(r)
        return jsonify(root=r["name"], path=rel, permissions=sorted(_perms(r)),
                       space={k: space[k] for k in ("unlimited", "total", "free") if k in space} if space else None,
                       quota={"used": q["used"], "limit": q["limit"], "complete": q["complete"]} if q else None,
                       entries=[
            {"name": e["name"], "type": "dir" if e["is_dir"] else "file", "size": e["bytes"],
             "modified": datetime.fromtimestamp(e["ts"], timezone.utc).isoformat(timespec="seconds"),
             "path": e["rel"]} for e in entries])
    parent = "/".join(rel.split("/")[:-1]) if rel else None
    return render_template("browse.html", root=r, roots=storage.available_roots(g.user, settings()),
                           rel=rel, crumbs=storage.breadcrumbs(rel), parent=parent, entries=entries,
                           tree=storage.folder_tree(r, rel, settings()["storage"]["show_hidden"], hidden, entries),
                           space=storage.space_of(r, rel), quota_status=quota.status(r),
                           perms=_perms(r), max_upload_mb=boot_config()["server"]["max_upload_mb"],
                           sort=sort, descending=descending,
                           max_file_size_mb=settings()["storage"]["max_file_size_mb"])


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
    return send_entry(r, rel, entry)


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
            storage.check_visible_name(settings(), backends.join_rel(rel, name))
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
    if saved:
        quota.invalidate(r)

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
        storage.check_visible_name(settings(), new_rel)
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
        storage.check_visible_name(settings(), backends.join_rel(parent, new_name))
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
        quota.invalidate(r)
        _audit("delete", r, rel)
        flash(_("«%(name)s» deleted.", name=backends.name_of(rel)), "info")
    except (OSError, backends.BackendError) as exc:
        flash(_("Could not delete: %(error)s", error=_reason(exc)), "error")
    return _back(r, parent)


def _is_broken_link(root: dict, rel: str) -> bool:
    """Un symlink roto en el disco local: no tiene ``stat`` pero se puede borrar."""
    local = root["backend"].local_path(backends.parent_rel(rel))
    return bool(local is not None and (local / backends.name_of(rel)).is_symlink())


# --------------------------------------------------------------------------- mover y copiar

def _transfer_perms(src: dict, dst: dict, move: bool) -> None:
    """Las mismas reglas que WebDAV: mover en la misma carpeta de StorageWeb es renombrar; entre carpetas es
    descargar + borrar en el origen y subir en el destino; copiar es descargar y subir."""
    same = src["name"] == dst["name"]
    if move and same:
        _require(src, "rename")
        return
    _require(src, "download")
    if move:
        _require(src, "delete")
    _require(dst, "upload")


@bp.route("/transfer", methods=["POST"])
@login_required
def transfer():
    """Mover o copiar los elementos elegidos (``items``, rutas en ``root``) a la carpeta ``dest_path`` de
    ``dest_root``. Nunca sobrescribe; lo que no se puede, se cuenta en ``errors``."""
    action = request.form.get("action", "")
    if action not in ("move", "copy"):
        abort(400)
    move = action == "move"
    src = _root(request.form.get("root", ""))
    dst = _root(request.form.get("dest_root", ""))
    dst_dir = _rel(request.form.get("dest_path", ""))
    _require_dir(dst, dst_dir)
    _transfer_perms(src, dst, move)
    cfg = settings()
    done, errors = [], []
    for raw in request.form.getlist("items"):
        try:
            rel = backends.clean_rel(raw)
            new_rel = files_core.transfer(cfg, src, rel, dst, dst_dir, move=move)
        except (files_core.FilesError, ValueError, PathError) as exc:
            errors.append(str(exc) if not isinstance(exc, PathError) else _("Invalid path: %(path)s", path=raw))
            continue
        done.append(backends.name_of(new_rel))
        _audit("rename" if move else "upload", src, rel, detail=f"{action}:{dst['name']}:/{new_rel}")
    if done:
        quota.invalidate(src, dst)
    if _wants_json():
        return jsonify(done=done, errors=errors), (200 if done or not errors else 400)
    if done:
        flash(ngettext("%(num)d item moved.", "%(num)d items moved.", len(done)) if move
              else ngettext("%(num)d item copied.", "%(num)d items copied.", len(done)), "info")
    for e in errors:
        flash(e, "error")
    return redirect(safe_next(request.form.get("next")))


@bp.route("/roots")
@login_required
def roots_json():
    """Las carpetas de StorageWeb del usuario, con sus permisos (para elegir el destino de mover o copiar)."""
    return jsonify(roots=[{"name": r["name"], "label": str(r["label"]), "read_only": bool(r["read_only"]),
                           "permissions": sorted(_perms(r))}
                          for r in storage.available_roots(g.user, settings())])


# --------------------------------------------------------------------------- ZIP

def _zip_response(items: list[tuple[dict, str]]):
    for root, _rel_ in items:
        _require(root, "download")
    name = files_core.zip_name(items)
    fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
    rv = Response(stream_with_context(files_core.zip_stream(settings(), items)), mimetype="application/zip")
    rv.headers["Content-Disposition"] = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"
    rv.headers["Content-Security-Policy"] = SANDBOX
    rv.headers["Cache-Control"] = "no-store"
    for root, rel in items:
        _audit("download", root, rel, detail="zip")
    return rv


@bp.route("/zip/<root>/", defaults={"sub": ""})
@bp.route("/zip/<root>/<path:sub>")
@login_required
def zip_folder(root, sub):
    """Una carpeta (o un archivo) como ZIP."""
    r = _root(root)
    rel = _rel(sub)
    if rel and _stat(r, rel) is None:
        abort(404)
    return _zip_response([(r, rel)])


@bp.route("/zip", methods=["POST"])
@login_required
def zip_selection():
    """Los elementos elegidos (``items``, rutas en ``root``) en un solo ZIP."""
    r = _root(request.form.get("root", ""))
    cfg = settings()
    items = []
    for raw in request.form.getlist("items"):
        try:
            rel = backends.clean_rel(raw)
        except PathError:
            continue
        name = backends.name_of(rel)
        # Como en la web: ni lo oculto para todos ni, si la web los oculta, lo que empieza por punto
        if not rel or storage.is_hidden(cfg, rel) or (name.startswith(".") and not cfg["storage"]["show_hidden"]):
            continue
        if _stat(r, rel) is not None:
            items.append((r, rel))
    if not items:
        abort(404)
    return _zip_response(items)


# --------------------------------------------------------------------------- buscar

SEARCH_LIMIT = 200


@bp.route("/search")
@login_required
def search():
    """Buscar archivos y carpetas por nombre en todas mis carpetas (o solo bajo una: ``root`` + ``path``)."""
    cfg = settings()
    query = request.args.get("q", "").strip()[:200]
    roots = storage.available_roots(g.user, cfg)
    scope_root = request.args.get("root", "")
    places = [(r, "") for r in roots]
    scope = None
    if scope_root:
        r = _root(scope_root)
        path = _rel(request.args.get("path", ""))
        places, scope = [(r, path)], {"root": r, "path": path}
    result = files_core.search(cfg, places, query, limit=SEARCH_LIMIT) if query else files_core.SearchResult()
    if _wants_json() or g.get("api_token") is not None:
        return jsonify(query=query, truncated=result.truncated, items=[
            {"root": i["root"]["name"], "path": i["rel"], "name": i["name"], "type": "dir" if i["is_dir"] else "file",
             "size": i["bytes"], "modified": datetime.fromtimestamp(i["ts"], timezone.utc).isoformat(timespec="seconds")}
            for i in result.items])
    perms = {r["name"]: _perms(r) for r in roots}
    return render_template("search.html", query=query, result=result, scope=scope, perms=perms,
                           limit=SEARCH_LIMIT)

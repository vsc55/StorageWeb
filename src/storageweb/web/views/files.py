"""Explorador de archivos: listar, subir, descargar, crear carpetas, renombrar y borrar.

Las operaciones van al ``backend`` de cada raíz (disco local, S3 o SMB) con rutas relativas a ella.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify, make_response, redirect,
                   render_template, request, stream_with_context, url_for)
from markupsafe import Markup, escape

from ... import patterns
from ... import metrics
from ...core import backends, markdown, preview, storage, tokens
from ...core import files as files_core
from ...core import quota
from ...core.permissions import PERMISSION_LABELS, effective_for_root, permissions_for
from ...core.security import UPLOAD_TMP_PREFIX, PathError, safe_filename
from ...db.repositories import audit
from ...i18n import _, format_datetime, format_size, ngettext
from ..context import boot_config, get_db, settings
from ..downloads import SANDBOX, send_entry
from ..guards import client_ip, login_required, safe_next, with_token

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
              detail=with_token(detail))


def _viewable(name: str) -> bool:
    """Si el archivo se abre en el visor (según ``preview.*``); para las plantillas del explorador y la búsqueda."""
    return preview.kind_of(name, settings()["preview"]) is not None


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
                           sort=sort, descending=descending, viewable=_viewable,
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


# --------------------------------------------------------------------------- visor (texto y Markdown)

def _md_link(root: dict, rel: str):
    """Dirección de un enlace del documento: http(s) y mailto tal cual; una ruta de la misma raíz, al visor o
    a la descarga; cualquier otra cosa (``javascript:``, ``data:``, otro servidor sin esquema, fuera de la
    raíz, oculto), ``None``: se ve el texto sin enlace."""
    def link(url: str) -> str | None:
        parts = urlsplit(url)
        if parts.scheme.lower() in ("http", "https", "mailto"):
            return url
        if parts.scheme or url.startswith("//"):
            return None
        target = preview.resolve(rel, url)
        if target is None or storage.is_hidden(settings(), target):
            return None
        kind = preview.kind_of(target, settings()["preview"])
        if kind is None:
            return url_for("files.download", root=root["name"], sub=target)
        anchor = f"#{markdown.HEADING_PREFIX}{markdown.slug(unquote(parts.fragment))}" \
            if parts.fragment and kind == "markdown" else ""
        return url_for("files.view", root=root["name"], sub=target) + anchor
    return link


def _md_image(root: dict, rel: str):
    """Solo imágenes de la misma raíz: las de fuera no se cargan (dirían a un tercero quién lee el documento)."""
    def image(url: str) -> str | None:
        parts = urlsplit(url)
        if parts.scheme or url.startswith("//"):
            return None
        target = preview.resolve(rel, url)
        if target is None or not preview.is_image(target) or storage.is_hidden(settings(), target):
            return None
        return url_for("files.download", root=root["name"], sub=target)
    return image


@bp.route("/diagram-frame")
def diagram_frame():
    """La página del marco aislado donde Mermaid dibuja un diagrama del visor. No lleva datos (el código llega
    por postMessage) ni necesita sesión. Su CSP la convierte en un origen opaco (``sandbox allow-scripts``):
    un fallo de Mermaid no alcanzaría las cookies ni la página. ``'self'`` y el origen explícito porque en un
    documento aislado algunos navegadores no casan ``'self'``."""
    options = settings()["preview"]
    if not (options["enabled"] and options["diagrams"]):
        abort(404)    # desactivados: Mermaid no llega al navegador
    origin = request.host_url.rstrip("/")
    rv = make_response(render_template("diagram_frame.html", dark=request.args.get("dark") == "1"))
    rv.headers["Content-Security-Policy"] = (
        f"sandbox allow-scripts; default-src 'none'; script-src 'self' {origin}; style-src 'unsafe-inline'; "
        f"img-src data:; font-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; "
        f"frame-ancestors 'self' {origin}")
    rv.headers["X-Frame-Options"] = "SAMEORIGIN"
    return rv


@bp.route("/view/<root>/<path:sub>")
@login_required
def view(root, sub):
    """El archivo en el navegador: Markdown renderizado (o su código) y texto con números de línea. Nunca HTML
    del usuario: el Markdown pasa por ``core/markdown.py`` y el HTML y el SVG se ven como código."""
    r = _root(root)
    _require(r, "download")
    rel = _rel(sub)
    entry = _stat(r, rel)
    if entry is None or entry.is_dir:
        abort(404)
    options = settings()["preview"]
    name = backends.name_of(rel)
    kind = preview.kind_of(name, options)
    if kind is None:     # visor desactivado, extensión fuera de la lista o bloqueada: se descarga
        return redirect(url_for("files.download", root=root, sub=rel))
    source = kind != "markdown" or request.args.get("source") == "1"
    try:
        content = preview.read_text(r["backend"], rel, entry.size, limit=options["max_mb"] * 1024 * 1024)
    except FileNotFoundError:
        abort(404)
    except backends.BackendError as exc:
        abort(502, description=exc.message)
    rendered = None
    if content.text is not None:
        _audit("download", r, rel, "view")
        if not source:
            try:
                rendered = markdown.render(content.text, link=_md_link(r, rel), image=_md_image(r, rel))
            except Exception:  # noqa: BLE001 — un documento raro no puede romper el visor: se ve su código
                current_app.logger.exception("Could not render %s:/%s as Markdown", r["name"], rel)
                source = True
    parent = "/".join(rel.split("/")[:-1])
    try:
        siblings = storage.list_directory(r, parent, settings()["storage"]["show_hidden"],
                                          hidden=patterns.of(settings()))
    except (PermissionError, backends.BackendError):
        siblings = []
    previous, following = preview.neighbours(siblings, rel, options)
    is_log = preview.extension(name) in preview.LOG
    lines = content.lines if source else []
    # Las líneas, ya escapadas, en Python: un bucle de la plantilla por línea es varias veces más lento
    lines_html = Markup("".join(
        f'<li class="lvl-{level}">{escape(line)}</li>' if (level := preview.log_level(line) if is_log else "")
        else f"<li>{escape(line)}</li>" for line in lines))
    return render_template(
        "view.html", root=r, rel=rel, name=name, parent=parent, crumbs=storage.breadcrumbs(parent), kind=kind,
        ext=preview.extension(name), size=format_size(entry.size),
        mtime=format_datetime(datetime.fromtimestamp(entry.mtime)) if entry.mtime else "",
        content=content, source=source, lines=lines, lines_html=lines_html,
        html=Markup(rendered.html) if rendered else None,   # seguro: lo genera core/markdown (todo escapado)
        toc=rendered.toc if rendered else [],
        diagrams=rendered.diagrams if rendered and options["diagrams"] else 0,   # desactivados: se ve el código
        previous=previous, following=following, max_mb=options["max_mb"])


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
    cfg = settings()
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
            quota.check(r, cfg, size)
            final = backend.unique_rel(rel, name)
            backend.store(tmp, final)
        except quota.QuotaExceeded as exc:
            errors.append(f"{name}: {exc.message}")
            tmp.unlink(missing_ok=True)
            continue
        except (OSError, backends.BackendError) as exc:
            current_app.logger.exception("Error saving %s", name)
            # Fuera del f-string: antes de Python 3.12 el extractor de textos no ve un _() dentro de uno
            reason = _reason(exc) or _("write error")
            errors.append(f"{name}: {reason}")
            tmp.unlink(missing_ok=True)
            continue
        saved.append(backends.name_of(final))
        quota.record(r, size)
        metrics.inc("storageweb_upload_bytes_total", size, via="web")
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
    same = src["name"] == dst["name"]
    for raw in request.form.getlist("items"):
        try:
            rel = backends.clean_rel(raw)
            size = 0 if move and same else quota.size_of(src["backend"], rel)
            quota.check(dst, cfg, size)  # mover dentro de la misma carpeta no ocupa más
            new_rel = files_core.transfer(cfg, src, rel, dst, dst_dir, move=move)
        except quota.QuotaExceeded as exc:
            errors.append(f"{backends.name_of(raw)}: {exc.message}")
            continue
        except (files_core.FilesError, ValueError, PathError) as exc:
            errors.append(str(exc) if not isinstance(exc, PathError) else _("Invalid path: %(path)s", path=raw))
            continue
        except backends.BackendError as exc:
            errors.append(f"{backends.name_of(raw)}: {exc}")
            continue
        done.append(backends.name_of(new_rel))
        if size:
            quota.record(dst, size)
            if move:
                quota.record(src, -size)
        _audit("rename" if move else "upload", src, rel, detail=f"{action}:{dst['name']}:/{new_rel}")
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
    return render_template("search.html", query=query, result=result, scope=scope, perms=perms, viewable=_viewable,
                           limit=SEARCH_LIMIT)

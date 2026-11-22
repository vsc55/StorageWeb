"""Enlaces para compartir (``core/links.py``).

* Públicas (sin sesión): ``/s/<token>`` (la página: contraseña si la tiene, el archivo, el contenido de la carpeta
  o el buzón para subir), ``/s/<token>/download`` y ``/s/<token>/zip`` (``?p=`` = ruta dentro de lo compartido) y
  ``/s/<token>/upload``. Siempre con ``Referrer-Policy: no-referrer`` (el token va en la dirección), sin caché y
  marcadas para no indexarse. Un token que no existe cuenta como infracción de la IP (``bad_token``) y una
  contraseña equivocada como un inicio de sesión fallido (limitador por IP y enlace).
* Con sesión: ``POST /links`` (crear, JSON, desde el explorador) y ``POST /links/<uid>/revoke`` (su dueño o un
  administrador).
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote

from flask import (Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, session,
                   stream_with_context, url_for)

from ... import metrics
from ...core import backends, ipban, links, quota, storage
from ...core import files as files_core
from ...core.permissions import is_admin
from ...core.security import UPLOAD_TMP_PREFIX, safe_filename
from ...db.repositories import share_links as repo
from ...i18n import _, format_datetime, format_size, ngettext
from ... import patterns
from ..context import boot_config, external_url, get_db, runtime, settings, throttle
from ..downloads import SANDBOX, send_entry
from ..guards import audit_event, client_ip, login_required, safe_next

bp = Blueprint("links", __name__)

UNLOCK_SECONDS = 3600          # una contraseña correcta vale una hora en ese navegador
_SESSION_KEY = "share_unlocked"


@bp.after_request
def _headers(response):
    if (request.endpoint or "").startswith("links.public"):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# --------------------------------------------------------------------------- crear y revocar (con sesión)

@bp.route("/links", methods=["POST"])
@login_required
def create():
    """Crea un enlace de ``root``/``path`` (el explorador). Contesta en JSON con su dirección."""
    cfg = settings()
    try:
        root = storage.find_root(g.user, cfg, request.form.get("root", ""))
    except storage.RootNotFound:
        abort(404)
    days = request.form.get("days", "")
    limit = request.form.get("max_downloads", "").strip()
    try:
        link, token = links.create(
            get_db(), cfg, runtime().secrets_key, g.user, root, request.form.get("path", ""),
            mode=request.form.get("mode", "download"), days=int(days) if days.strip() else None,
            password=request.form.get("password", ""), max_downloads=int(limit) if limit else None,
            note=request.form.get("note", ""))
    except ValueError:
        return jsonify(error=_("Write whole numbers for the days and the downloads.")), 400
    except links.LinkError as exc:
        return jsonify(error=exc.message), 400
    detail = ", ".join(filter(None, [link["mode"], f"{days}d" if days else None,
                                     "password" if link["password_hash"] else None,
                                     f"max={link['max_downloads']}" if link["max_downloads"] else None]))
    audit_event("link_created", f"{link['root']}:/{link['rel']}", detail)
    _record(link, "created", detail=f"{g.user['username']}: {detail}")
    return jsonify(url=external_url("links.public", token=token), uid=link["uid"], mode=link["mode"],
                   expires=format_datetime(link["expires_at"]) if link["expires_at"] else "",
                   mine=url_for("profile.section", section="links"))


@bp.route("/links/<uid>/revoke", methods=["POST"])
@login_required
def revoke(uid: str):
    """Deja de compartir: el dueño, o un administrador (cualquiera). El enlace y su historial se quedan."""
    link = links.revoke(get_db(), uid, g.user, admin=is_admin(g.user), ip=client_ip(),
                        user_agent=request.user_agent.string)
    if link is None:
        abort(404)
    audit_event("link_revoked", f"{link['root']}:/{link['rel']}", f"owner={link['owner']}")
    flash(_("Link removed: it no longer works."), "info")
    return redirect(safe_next(request.form.get("next")))


# --------------------------------------------------------------------------- las páginas públicas

def _gone(code: int = 404):
    return render_template("link_gone.html", current_user=None, code=code), code


def _open(token: str):
    """``(enlace, dueño, carpeta, permisos)`` o una respuesta de error (no existe, caducó, ya no funciona)."""
    link = links.find(get_db(), token)
    if link is None:
        ipban.offense(get_db(), settings(), client_ip(), "bad_token")
        return None, _gone(404)
    state = links.state(link)
    if state != "ok":
        _record(link, "refused", detail=state)
        return None, _gone(410)
    if not links.enabled(settings()):
        _record(link, "refused", detail="off")
        return None, _gone(404)
    try:
        owner, root, perms = links.resolve(get_db(), settings(), link)
    except links.LinkError:
        _record(link, "refused", detail="unavailable")
        return None, _gone(404)
    return (link, owner, root, perms), None


def _record(link, event: str, *, path: str | None = None, detail: str | None = None) -> None:
    """Apunta el suceso con la IP y el navegador de esta petición (la trazabilidad del enlace)."""
    links.record(get_db(), link, event, path=path, ip=client_ip(), user_agent=request.user_agent.string,
                 detail=detail)


def _unlocked(link) -> bool:
    if not link["password_hash"]:
        return True
    until = (session.get(_SESSION_KEY) or {}).get(link["uid"], 0)
    return until > time.time()


def _unlock(link) -> None:
    opened = {k: v for k, v in (session.get(_SESSION_KEY) or {}).items() if v > time.time()}
    opened[link["uid"]] = time.time() + UNLOCK_SECONDS
    session[_SESSION_KEY] = opened


def _target(link, root, sub: str) -> tuple[str, object]:
    """La ruta en la carpeta de StorageWeb y su ``Entry``; 404 si sale de lo compartido, está oculta o no existe."""
    try:
        rel = links.inside(link, sub)
    except links.LinkError:
        abort(404)
    if storage.is_hidden(settings(), rel):
        abort(404)
    try:
        entry = root["backend"].stat(rel)
    except backends.BackendError as exc:
        abort(502, description=exc.message)
    if entry is None:
        abort(404)
    return rel, entry


def _audit(action: str, link, root: dict, rel: str, detail: str = "") -> None:
    audit_event(action, f"{root['name']}:/{rel}",
                " ".join(filter(None, [f"link={link['uid'][:8]}", f"owner={link['owner']}", detail])))


@bp.route("/s/<token>", methods=["GET", "POST"])
def public(token: str):
    opened, error = _open(token)
    if error:
        return error
    link, owner, root, _perms = opened
    if request.method == "POST" and link["password_hash"] and not _unlocked(link):
        return _try_password(token, link, root)
    if not _unlocked(link):
        if request.method == "GET":
            _record(link, "opened", detail="password")
        return render_template("share.html", current_user=None, state="locked", link=link, token=token,
                               owner=owner)
    cfg = settings()
    context = dict(current_user=None, state="open", link=link, token=token, owner=owner,
                   expires=format_datetime(link["expires_at"]) if link["expires_at"] else "",
                   left=(link["max_downloads"] - link["downloads"]) if link["max_downloads"] else None)
    if link["mode"] == "upload":
        _record(link, "opened")
        context.update(max_upload_mb=boot_config()["server"]["max_upload_mb"],
                       max_file_size_mb=cfg["storage"]["max_file_size_mb"])
        return render_template("share.html", **context)
    sub = request.args.get("p", "")
    rel, entry = _target(link, root, sub)
    _record(link, "opened", path=rel)
    if not entry.is_dir:
        repo.touch(get_db(), link["id"])
        context.update(file={"name": backends.name_of(rel), "size": format_size(entry.size),
                             "mtime": format_datetime(datetime.fromtimestamp(entry.mtime, timezone.utc))},
                       sub=sub)
        return render_template("share.html", **context)
    try:
        listing = storage.list_directory(root, rel, cfg["storage"]["show_hidden"], hidden=patterns.of(cfg))
    except (PermissionError, backends.BackendError):
        abort(502)
    size = cfg["storage"]["page_size"]
    here = sub.strip("/")
    crumbs = [("", link["rel"].split("/")[-1] if link["rel"] else root["label"])]
    acc = []
    for part in [p for p in here.split("/") if p]:
        acc.append(part)
        crumbs.append(("/".join(acc), part))
    rows = [{"name": e["name"], "is_dir": e["is_dir"], "size": e["size"], "mtime": e["mtime"],
             "p": backends.join_rel(here, e["name"]) if here else e["name"]} for e in listing]
    context.update(rows=rows[:size], more=max(0, len(rows) - size), crumbs=crumbs, sub=here,
                   parent=("/".join(here.split("/")[:-1]) if here else None))
    repo.touch(get_db(), link["id"])
    return render_template("share.html", **context)


def _try_password(token: str, link, root):
    cfg = settings()
    ip = client_ip()
    limiter = throttle()
    limiter.configure(cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60)
    if limiter.is_blocked(ip, link["uid"], scope="link"):
        _record(link, "refused", detail="locked")
        flash(_("Too many failed attempts. Wait a few minutes."), "error")
    elif links.check_password(link, request.form.get("password", "")):
        limiter.success(ip, link["uid"], scope="link")
        _unlock(link)
        _record(link, "unlocked")
        return redirect(url_for("links.public", token=token))
    else:
        limiter.failure(ip, link["uid"], scope="link")
        ipban.offense(get_db(), cfg, ip, "login_failed")
        _audit("link_password_failed", link, root, link["rel"])
        _record(link, "password_failed")
        flash(_("Wrong password."), "error")
    return redirect(url_for("links.public", token=token))


def _counted(link) -> bool:
    """Suma la descarga; False (y nada que descargar) si ya no quedaban."""
    return repo.count_download(get_db(), link["id"])


@bp.route("/s/<token>/download")
def public_download(token: str):
    opened, error = _open(token)
    if error:
        return error
    link, _owner, root, _perms = opened
    if link["mode"] != "download" or not _unlocked(link):
        abort(404)
    rel, entry = _target(link, root, request.args.get("p", ""))
    if entry.is_dir:
        abort(404)
    if not _counted(link):
        _record(link, "refused", path=rel, detail="used_up")
        return _gone(410)
    _audit("link_download", link, root, rel)
    _record(link, "download", path=rel, detail=str(entry.size))
    metrics.inc("storageweb_link_downloads_total")
    return send_entry(root, rel, entry)


@bp.route("/s/<token>/zip")
def public_zip(token: str):
    opened, error = _open(token)
    if error:
        return error
    link, _owner, root, _perms = opened
    if link["mode"] != "download" or not _unlocked(link) or not link["is_dir"]:
        abort(404)
    rel, entry = _target(link, root, request.args.get("p", ""))
    if not entry.is_dir:
        abort(404)
    if not _counted(link):
        _record(link, "refused", path=rel, detail="used_up")
        return _gone(410)
    _audit("link_download", link, root, rel, "zip")
    _record(link, "zip", path=rel)
    name = files_core.zip_name([(root, rel)])
    fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
    rv = Response(stream_with_context(files_core.zip_stream(settings(), [(root, rel)])), mimetype="application/zip")
    rv.headers["Content-Disposition"] = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"
    rv.headers["Content-Security-Policy"] = SANDBOX
    return rv


@bp.route("/s/<token>/upload", methods=["POST"])
def public_upload(token: str):
    opened, error = _open(token)
    if error:
        return error
    link, _owner, root, _perms = opened
    if link["mode"] != "upload" or not _unlocked(link):
        abort(404)
    rel, entry = _target(link, root, "")
    if not entry.is_dir:
        abort(404)
    cfg = settings()
    backend = root["backend"]
    limit = int(cfg["storage"]["max_file_size_mb"] or 0) * 1024 * 1024
    saved, errors = [], []
    for item in request.files.getlist("files"):
        if not item or not item.filename:
            continue
        try:
            name = safe_filename(item.filename)
            storage.check_visible_name(cfg, backends.join_rel(rel, name))
        except ValueError as exc:
            errors.append(f"{item.filename}: {exc}")
            continue
        tmp = backend.staging_dir(rel) / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
        try:
            item.save(tmp)
            size = tmp.stat().st_size
            if limit and size > limit:
                raise files_core.FilesError(_("It is larger than %(size)s.", size=format_size(limit)))
            quota.check(root, cfg, size)
            final = backend.unique_rel(rel, name)      # nunca sobrescribe: «nombre (1).ext»
            backend.store(tmp, final)
        except (quota.QuotaExceeded, files_core.FilesError) as exc:
            errors.append(f"{name}: {getattr(exc, 'message', None) or exc}")
            _record(link, "refused", path=backends.join_rel(rel, name),
                    detail="quota" if isinstance(exc, quota.QuotaExceeded) else "too_large")
            tmp.unlink(missing_ok=True)
            continue
        except (OSError, backends.BackendError):
            errors.append(f"{name}: {_('write error')}")
            tmp.unlink(missing_ok=True)
            continue
        quota.record(root, size)
        repo.count_upload(get_db(), link["id"])
        saved.append(backends.name_of(final))
        _audit("link_upload", link, root, final, str(size))
        _record(link, "upload", path=final, detail=str(size))
    if saved:
        flash(ngettext("%(num)d file uploaded.", "%(num)d files uploaded.", len(saved)), "info")
    for e in errors:
        flash(e, "error")
    return redirect(url_for("links.public", token=token))


# --------------------------------------------------------------------------- actividad (con sesión)

def _own_link(uid: str):
    """El enlace ``uid`` si es de quien pregunta o si es administrador; si no, 404. Uno que la limpieza ya borró
    se reconstruye desde su historial (:func:`links.history_link`) y es de quien figura como dueño en él."""
    link = links.get(get_db(), uid)
    if link is None:
        link = links.history_link(get_db(), uid)
        if link is None or (link["owner"] != g.user["username"] and not is_admin(g.user)):
            abort(404)
        return link
    if link["user_id"] != g.user["id"] and not is_admin(g.user):
        abort(404)
    return link


@bp.route("/links/<uid>/activity")
@login_required
def activity(uid: str):
    """Todo lo que ha pasado con un enlace: cuándo, qué, desde qué IP y con qué navegador."""
    link = _own_link(uid)
    events = links.events(get_db(), uid)
    summary = links.activity(get_db(), [uid]).get(uid, {"opened": 0, "downloads": 0, "uploads": 0, "refused": 0,
                                                       "last": ""})
    return render_template("link_activity.html", link=link, events=events, summary=summary,
                           state=links.state(link), STATE_LABELS=links.STATE_LABELS, MODE_LABELS=links.MODE_LABELS,
                           EVENT_LABELS=links.EVENT_LABELS, REFUSED_LABELS=links.REFUSED_LABELS,
                           back=safe_next(request.args.get("next")) if request.args.get("next")
                           else url_for("profile.section", section="links",
                                        show="deleted" if link.get("deleted") else None)
                           if isinstance(link, dict) else url_for("profile.section", section="links"))


@bp.route("/links/<uid>/activity.csv")
@login_required
def activity_csv(uid: str):
    """El historial en CSV (para guardarlo o cruzarlo con otros registros)."""
    import csv
    import io
    link = _own_link(uid)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["at", "event", "path", "ip", "user_agent", "detail", "link", "owner", "target"])
    for e in links.events(get_db(), uid):
        writer.writerow([e["at"], e["event"], e["path"] or "", e["ip"] or "", e["user_agent"] or "", e["detail"] or "",
                         e["link_uid"], e["owner"] or "", e["target"] or ""])
    audit_event("link_activity_exported", f"{link['root']}:/{link['rel']}", f"owner={link['owner']}")
    rv = Response(out.getvalue(), mimetype="text/csv; charset=utf-8")
    rv.headers["Content-Disposition"] = f'attachment; filename="link-{uid[:8]}.csv"'
    rv.headers["Content-Security-Policy"] = SANDBOX
    return rv

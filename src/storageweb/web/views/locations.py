"""Sistema → Almacenamiento externo (solo rol admin): ubicaciones S3, SMB… (un tipo por backend).

Edita ``storage.locations`` como el resto de ajustes (se guarda la diferencia con los valores
predeterminados; bloqueado si viene de config.json o del entorno). Los secretos no se muestran:
dejarlos vacíos conserva los guardados.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ...core import locations as core
from ...i18n import _, _l
from ..context import settings
from ..guards import admin_required, audit_event
from .. import search
from .access import lock_context, refuse_if_locked
from .settings.common import save_partial

bp = Blueprint("locations", __name__, url_prefix="/admin/storage")

PATH = "storage.locations"


def _locations() -> list[dict]:
    return settings()["storage"]["locations"]


def _lock_context(loc: dict | None = None) -> dict:
    return lock_context("locations", loc)


def _refuse_if_locked(loc: dict | None):
    return refuse_if_locked("locations", loc, "locations.index")


def _render(loc: dict, original: str | None, status: int = 200, error: str | None = None):
    title = (loc["label"] or loc["name"]) if original else _("New storage location")
    stored = core.find(_locations(), original) if original else None
    schema = core.schema(loc["type"])
    has_secret = {name: bool(stored and stored.get(name)) for name in schema.secrets}
    return render_template("admin/locations/edit.html", loc=loc, schema=schema, original=original, title=title,
                           error=error, used_by=core.users_of(settings(), original) if original else [],
                           has_secret=has_secret, **_lock_context(stored)), status


@bp.route("/")
@admin_required
def index():
    cfg = settings()
    rows = [{"loc": loc, "where": core.describe(loc), "used_by": core.users_of(cfg, loc["name"])}
            for loc in _locations()]
    return render_template("admin/locations/index.html", rows=rows, schemas=core.schemas(), **_lock_context())


def _store(original: str | None):
    stored = core.find(_locations(), original) if original else None
    refused = _refuse_if_locked(stored)
    if refused:
        return refused
    try:
        loc = core.from_form(request.form, stored)
    except core.LocationError:
        abort(400)
    try:
        new_list = core.replace(_locations(), original, loc)
    except core.LocationError as exc:
        return _render(loc, original, 400, exc.message)
    _draft, error = save_partial(lambda: {"storage": {"locations": new_list}}, strict=True)
    if error:
        return _render(loc, original, 400, str(error))
    audit_event("location_created" if original is None else "location_updated", loc["name"], core.describe(loc))
    flash(_("Storage location «%(label)s» saved.", label=loc["label"] or loc["name"]), "info")
    if request.form.get("then") == "test":
        return _test(loc["name"])
    return redirect(url_for("locations.index") + f"#loc-{loc['name']}")


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    if request.method == "POST":
        return _store(None)
    try:
        loc = core.blank(request.args.get("type", ""))
    except core.LocationError:
        abort(404)
    return _render(loc, None)


@bp.route("/<name>", methods=["GET", "POST"])
@admin_required
def edit(name: str):
    loc = core.find(_locations(), name)
    if loc is None:
        abort(404)
    if request.method == "POST":
        return _store(name)
    return _render(loc, name)


def _test(name: str):
    loc = core.find(_locations(), name)
    if loc is None:
        abort(404)
    error = core.test(settings(), loc)
    audit_event("location_tested", name, error or "ok")
    if error:
        flash(_("The connection to «%(label)s» failed: %(error)s", label=loc["label"], error=error), "error")
    else:
        flash(_("Connection to «%(label)s» working: %(where)s", label=loc["label"], where=core.describe(loc)), "info")
    return redirect(url_for("locations.edit", name=name))


@bp.route("/<name>/test", methods=["POST"])
@admin_required
def test(name: str):
    return _test(name)


@bp.route("/<name>/delete", methods=["POST"])
@admin_required
def delete(name: str):
    loc = core.find(_locations(), name)
    if loc is None:
        abort(404)
    refused = _refuse_if_locked(loc)
    if refused:
        return refused
    try:
        new_list = core.remove(settings(), name)
    except core.LocationError as exc:
        flash(exc.message, "error")
        return redirect(url_for("locations.edit", name=name))
    _draft, error = save_partial(lambda: {"storage": {"locations": new_list}}, strict=True)
    if error:
        flash(_("The changes were not saved: %(error)s", error=error), "error")
        return redirect(url_for("locations.edit", name=name))
    audit_event("location_deleted", name, core.describe(loc))
    flash(_("Storage location «%(label)s» removed. Its files are still there.", label=loc["label"]), "info")
    return redirect(url_for("locations.index"))


@search.provider("location", _l("Storage locations"), order=40)
def _search_locations(terms, conn, cfg):
    return [search.item("location", loc["label"], core.describe(loc), url_for("locations.edit", name=loc["name"]),
                        icon="folder")
            for loc in cfg["storage"]["locations"]
            if search.matches(terms, loc["label"], loc["name"], loc["type"], core.describe(loc))]

"""Administración de grupos (solo rol admin), con dos vistas para elegir (Personas → Grupos):

* **Lista** (``/admin/groups/list``) + ficha de cada grupo (``/admin/groups/<id>``).
* **Paneles** (``/admin/groups/panel``): lista a la izquierda y detalle con pestañas.

Y la **matriz de accesos** (``/admin/groups/matrix``, en Acceso): acceso de cada grupo a cada
carpeta compartida. No es una vista de grupos, así que ``/admin/groups/`` nunca lleva a ella.

Todas comparten las acciones (alta, edición, miembros, baja); ``next`` decide a dónde volver.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from ...core import groups as group_core
from ...core.accounts import SOURCE_LABELS
from ...providers.entra import directory as entra_directory
from ...db.repositories import users
from ...db.repositories import groups as repo
from ...i18n import _
from ...settings import ConfigError, runtime_view
from ..context import get_db, invalidate_settings, runtime, settings
from ..forms import back
from ..guards import admin_required, audit_event

bp = Blueprint("groups", __name__, url_prefix="/admin/groups")

VIEWS = ("list", "panel")  # vistas de Personas → Grupos; la matriz está en Acceso
TABS = ("members", "shares", "link")


_audit = audit_event


def _shares() -> list[dict]:
    return settings()["storage"]["shares"]




def _remember(view: str) -> None:
    session["groups_view"] = view


@bp.app_template_filter("group_label")
def _group_label(group) -> str:
    return group_core.label(group)


@bp.app_template_filter("group_description")
def _group_description(group) -> str:
    return group_core.description(group)


def entra_names(ids) -> dict[str, str]:
    """Nombres de grupos de Entra ID para mostrarlos junto a su Object ID (vacío si no se pueden leer)."""
    return entra_directory.names_for(settings()["auth"]["entra"], ids)


@bp.route("/entra/search")
@admin_required
def entra_search():
    """Buscador de grupos de Entra ID por nombre para el formulario de alta (JSON)."""
    return jsonify(groups=entra_directory.search_groups(settings()["auth"]["entra"], request.args.get("q", "")),
                   available=entra_directory.configured(settings()["auth"]["entra"]))


@bp.context_processor
def _labels():
    return {"GROUP_SOURCE_LABELS": group_core.GROUP_SOURCE_LABELS, "SOURCE_LABELS": SOURCE_LABELS,
            "GROUP_SOURCES": group_core.GROUP_SOURCES}


def _get_group(group_id: int):
    group = repo.get_by_id(get_db(), group_id)
    if group is None:
        abort(404)
    return group


def _form_data() -> dict:
    f = request.form
    return {"label": f.get("label", "").strip(), "description": f.get("description", "").strip(),
            "source": f.get("source", "local"), "external_id": f.get("external_id", "").strip()}


# --------------------------------------------------------------------------- entrada y vista A

@bp.route("/")
@admin_required
def index():
    view = session.get("groups_view")
    return redirect(url_for(f"groups.{view if view in VIEWS else 'list'}_view"))


@bp.route("/list")
@admin_required
def list_view():
    _remember("list")
    search = request.args.get("q", "").strip()
    source = request.args.get("source", "")
    source = source if source in group_core.GROUP_SOURCES else ""
    rows = repo.list_all(get_db(), search=search, source=source or None)
    shares = _shares()
    detected = group_core.detected(get_db(), shares)
    return render_template("admin/groups/list.html", groups=rows, search=search, source=source,
                           shares_by_group={r["id"]: group_core.shares_of(r, shares) for r in rows},
                           detected=detected, names=entra_names(
                               [d["id"] for d in detected] + [r["external_id"] for r in rows if r["external_id"]]))


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    form = {"name": request.args.get("name", ""), "label": request.args.get("label", ""), "description": "",
            "source": request.args.get("source", "local"), "external_id": request.args.get("external_id", "")}
    if form["source"] not in group_core.GROUP_SOURCES:
        form["source"] = "local"
    if request.method == "POST":
        form = {**_form_data(), "name": request.form.get("name", "").strip()}
        if form["source"] == "entra" and form["external_id"] and not form["label"]:
            form["label"] = entra_names([form["external_id"]]).get(form["external_id"].lower(), "")
        try:
            gid = group_core.create_group(get_db(), **form)
        except group_core.GroupError as exc:
            flash(exc.message, "error")
        else:
            group = repo.get_by_id(get_db(), gid)
            _audit("group_created", group["name"], f"{group['source']}:{group['external_id'] or ''}")
            flash(_("Group «%(name)s» created.", name=group_core.label(group)), "info")
            return back(url_for("groups.edit", group_id=gid))
    return render_template("admin/groups/form.html", group=None, form=form, next=request.args.get("next", ""))


@bp.route("/<int:group_id>", methods=["GET", "POST"])
@admin_required
def edit(group_id: int):
    group = _get_group(group_id)
    form = dict(group)
    if request.method == "POST" and group["builtin"]:
        flash(_("This group comes with StorageWeb and cannot be changed."), "error")
        return back(url_for("groups.edit", group_id=group_id))
    if request.method == "POST":
        data = _form_data()
        try:
            group_core.update_group(get_db(), group, **data)
        except group_core.GroupError as exc:
            flash(exc.message, "error")
            form.update(data)
        else:
            _audit("group_updated", group["name"], f"{data['source']}:{data['external_id']}")
            flash(_("Changes saved."), "info")
            return back(url_for("groups.edit", group_id=group_id))
    return render_template("admin/groups/form.html", group=group, form=form,
                           members=group_core.members(get_db(), group),
                           shares=group_core.shares_of(group, _shares()), next="")


@bp.route("/<int:group_id>/delete", methods=["POST"])
@admin_required
def delete(group_id: int):
    group = _get_group(group_id)
    try:
        group_core.delete_group(get_db(), group)
    except group_core.GroupError as exc:
        flash(exc.message, "error")
        return redirect(url_for("groups.edit", group_id=group_id))
    _audit("group_deleted", group["name"])
    flash(_("Group «%(name)s» deleted. Users and files have not been touched.", name=group["label"]), "info")
    return redirect(url_for("groups.index"))


@bp.route("/<int:group_id>/members", methods=["POST"])
@admin_required
def member_add(group_id: int):
    group = _get_group(group_id)
    username = request.form.get("username", "").strip()
    user = users.get_by_username(get_db(), username) if username else None
    if user is None:
        flash(_("The user %(name)s does not exist.", name=repr(username)), "error")
    else:
        group_core.add_member(get_db(), group, user)
        _audit("group_member_added", group["name"], user["username"])
        flash(_("«%(user)s» added to the group «%(group)s».", user=user["username"],
                group=group_core.label(group)), "info")
    return back(url_for("groups.edit", group_id=group_id))


@bp.route("/<int:group_id>/members/<int:user_id>/remove", methods=["POST"])
@admin_required
def member_remove(group_id: int, user_id: int):
    group = _get_group(group_id)
    user = users.get_by_id(get_db(), user_id)
    if user is None:
        abort(404)
    try:
        group_core.remove_member(get_db(), group, user, g.user)
    except group_core.GroupError as exc:
        flash(exc.message, "error")
    else:
        _audit("group_member_removed", group["name"], user["username"])
        flash(_("«%(user)s» removed from the group «%(group)s».", user=user["username"],
                group=group_core.label(group)), "info")
    return back(url_for("groups.edit", group_id=group_id))


# --------------------------------------------------------------------------- vista B

@bp.route("/panel")
@admin_required
def panel_view():
    _remember("panel")
    search = request.args.get("q", "").strip()
    rows = repo.list_all(get_db(), search=search)
    current = None
    wanted = request.args.get("g", type=int)
    for row in rows:
        if row["id"] == wanted or current is None:
            current = row
            if row["id"] == wanted:
                break
    tab = request.args.get("tab", "members")
    tab = tab if tab in TABS else "members"
    ctx = {}
    if current is not None:
        ctx = {"members": group_core.members(get_db(), current),
               "shares": group_core.shares_of(current, _shares()),
               "form": dict(current)}
    return render_template("admin/groups/panel.html", groups=rows, current=current, tab=tab, search=search,
                           detected=(detected := group_core.detected(get_db(), _shares())),
                           names=entra_names([d["id"] for d in detected]), **ctx)


# --------------------------------------------------------------------------- vista C

def _matrix(rows, shares) -> list[dict]:
    return [{"group": r, "cells": [{"share": s, "level": group_core.share_level(r, s),
                                     "everyone": group_core.open_to_everyone(s)} for s in shares]}
            for r in rows]


@bp.route("/matrix", methods=["GET", "POST"])
@admin_required
def matrix_view():
    rows = repo.list_all(get_db())
    if request.method == "POST":
        new = runtime_view(settings())
        shares = new["storage"]["shares"]
        changes = []
        for row in rows:
            for share in list(shares):
                value = request.form.get(f"access-{row['id']}-{share['name']}")
                if value is None or group_core.open_to_everyone(share):
                    continue
                current = next(s for s in shares if s["name"] == share["name"])
                if value != group_core.share_level(row, current):
                    try:
                        shares = group_core.apply_access(shares, row, share["name"], value)
                    except group_core.GroupError as exc:
                        flash(exc.message, "error")
                        return redirect(url_for("groups.matrix_view"))
                    changes.append(f"{row['name']}@{share['name']}={value}")
        if changes:
            new["storage"]["shares"] = shares
            try:
                runtime().save(get_db(), new, g.user["username"], strict=True)
            except ConfigError as exc:
                flash(_("The changes were not saved: %(error)s", error=exc), "error")
                return redirect(url_for("groups.matrix_view"))
            invalidate_settings()
            _audit("group_access_updated", None, ", ".join(changes)[:500])
            flash(_("Access saved: %(count)s changes.", count=len(changes)), "info")
        else:
            flash(_("There were no changes."), "info")
        return redirect(url_for("groups.matrix_view"))
    shares = _shares()
    names = {r["name"] for r in rows} | {r["external_id"] for r in rows if r["external_id"]}
    unregistered = sorted({ref for s in shares for ref in s["groups"] if ref not in names})
    return render_template("admin/groups/matrix.html", shares=shares, matrix=_matrix(rows, shares),
                           unregistered=unregistered, locked_message=runtime().lock_notice("storage.shares"))

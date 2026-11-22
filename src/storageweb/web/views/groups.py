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
from ... import providers
from ...core import accounts
from ...db.repositories import users
from ...db.repositories import groups as repo
from ...i18n import _, _l, ngettext
from ...settings import ConfigError, runtime_view
from ..context import get_db, invalidate_settings, runtime, settings
from ..forms import back
from ..guards import admin_required, audit_event
from .. import search

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


def _directories(only: str | None = None):
    """(método, directorio) de los métodos de inicio de sesión que tienen directorio de grupos."""
    cfg = settings()
    for method in providers.methods():
        if only and method.key != only:
            continue
        found = method.directory(method.section(cfg))
        if found is not None:
            yield method, found


def directory_lookup(ids, only: str | None = None) -> dict[str, tuple[str, str]]:
    """``{id: (método, nombre)}`` de los grupos externos que el directorio de su proveedor sabe nombrar."""
    ids = list(ids)
    found: dict[str, tuple[str, str]] = {}
    for method, directory in _directories(only):
        for ref, name in directory.names_for([i for i in ids if i not in found]).items():
            found[ref] = (method.key, name)
    return found


def directory_details(ids, only: str | None = None) -> dict[str, dict]:
    """``{id: {"name", "description"}}`` de los grupos externos que conoce el directorio de su proveedor."""
    ids = list(ids)
    found: dict[str, dict] = {}
    for _method, directory in _directories(only):
        found.update({ref: info for ref, info in directory.details([i for i in ids if i not in found]).items()
                      if ref not in found})
    return found


def directory_names(ids, only: str | None = None) -> dict[str, str]:
    """Nombres legibles de grupos externos (Object IDs de Entra ID…); vacío si no se pueden leer."""
    return {ref: name for ref, (_key, name) in directory_lookup(ids, only).items()}


@bp.route("/directory/<method>/search")
@admin_required
def directory_search(method: str):
    """Buscador de grupos por nombre en el directorio de un método, para el formulario de alta (JSON)."""
    for _m, directory in _directories(method):
        found = directory.search(request.args.get("q", ""))
        for item in found:  # identificador que se propondría al darlo de alta
            item["suggested_name"] = group_core.suggest_name(get_db(), item.get("name"), item.get("id"))
        return jsonify(groups=found, available=directory.configured())
    abort(404)


def _group_methods() -> list[dict]:
    """Orígenes de grupo que vienen de un método de inicio de sesión, para el formulario."""
    cfg = settings()
    return [{"key": m.key, "label": m.label, "hint": m.group_hint, "id_help": m.group_id_help,
             "search": url_for("groups.directory_search", method=m.key)
             if m.directory(m.section(cfg)) is not None else ""}
            for m in providers.methods() if m.external_groups]


@bp.context_processor
def _labels():
    return {"GROUP_SOURCE_LABELS": group_core.group_source_labels(), "SOURCE_LABELS": accounts.source_labels(),
            "GROUP_SOURCES": group_core.group_sources(), "group_methods": _group_methods}


def _get_group(group_uid: str):
    """El grupo por su identificador público (el de las direcciones); 404 si no existe."""
    group = repo.get_by_uid(get_db(), group_uid)
    if group is None:
        abort(404)
    return group


def _form_data() -> dict:
    f = request.form
    return {"label": f.get("label", "").strip(), "description": f.get("description", "").strip(),
            "source": f.get("source", group_core.LOCAL), "external_id": f.get("external_id", "").strip()}


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
    source = source if source in group_core.group_sources() else ""
    rows = repo.list_all(get_db(), search=search, source=source or None)
    shares = _shares()
    detected = group_core.detected(get_db(), shares)
    return render_template("admin/groups/list.html", groups=rows, search=search, source=source,
                           shares_by_group={r["id"]: group_core.shares_of(r, shares) for r in rows},
                           detected=detected, names=directory_names(
                               [d["id"] for d in detected] + [r["external_id"] for r in rows if r["external_id"]]))


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    form = {"name": request.args.get("name", ""), "label": request.args.get("label", ""),
            "description": request.args.get("description", ""),
            "source": request.args.get("source", group_core.LOCAL), "external_id": request.args.get("external_id", "")}
    if form["source"] not in group_core.group_sources():
        form["source"] = group_core.LOCAL
    if request.method == "GET":
        _fill_from_directory(form)
    if request.method == "POST":
        form = {**_form_data(), "name": request.form.get("name", "").strip()}
        _fill_from_directory(form)
        try:
            gid = group_core.create_group(get_db(), **form)
        except group_core.GroupError as exc:
            flash(exc.message, "error")
        else:
            group = repo.get_by_id(get_db(), gid)
            _audit("group_created", group["name"], f"{group['source']}:{group['external_id'] or ''}")
            flash(_("Group «%(name)s» created.", name=group_core.label(group)), "info")
            return back(url_for("groups.edit", group_uid=group["uid"]))
    return render_template("admin/groups/form.html", group=None, form=form, next=request.args.get("next", ""),
                           from_directory=False)


def _fill_from_directory(form: dict) -> None:
    """Grupo externo: lo que falte (nombre, descripción, identificador) sale del directorio de su proveedor
    (Entra ID: nombre y descripción del grupo); el identificador se propone a partir del nombre."""
    if form["source"] == group_core.LOCAL or not form["external_id"]:
        return
    if not form["label"] or not form["description"]:
        info = directory_details([form["external_id"]], form["source"]).get(form["external_id"].lower(), {})
        form["label"] = form["label"] or info.get("name", "")
        if not form["description"] and request.method == "GET":  # al guardar, vacía puede ser a propósito
            form["description"] = info.get("description", "")
    if not form["name"]:
        form["name"] = group_core.suggest_name(get_db(), form["label"], form["external_id"])


@bp.route("/register-detected", methods=["POST"])
@admin_required
def register_detected():
    """Da de alta de una vez los grupos sin dar de alta que llegan de un proveedor, con el nombre y la
    descripción de su directorio (Entra ID) y un identificador sacado del nombre."""
    pending = [d for d in group_core.detected(get_db(), _shares()) if d["source"]]
    wanted = set(request.form.getlist("id"))
    if wanted:
        pending = [d for d in pending if d["id"] in wanted]
    infos = {}
    for source in {d["source"] for d in pending}:
        infos.update(directory_details([d["id"] for d in pending if d["source"] == source], source))
    created, errors = [], []
    for d in pending:
        try:
            gid = group_core.register_external(get_db(), source=d["source"], external_id=d["id"],
                                               info=infos.get(d["id"]))
        except group_core.GroupError as exc:
            errors.append(f"{d['id']}: {exc.message}")
            continue
        group = repo.get_by_id(get_db(), gid)
        _audit("group_created", group["name"], f"{group['source']}:{group['external_id'] or ''}")
        created.append(group_core.label(group))
    if created:
        flash(ngettext("Group registered: %(names)s.", "%(num)s groups registered: %(names)s.", len(created),
                       names=", ".join(created)), "info")
    for error in errors:
        flash(error, "error")
    if not created and not errors:
        flash(_("There were no groups to register."), "info")
    return back(url_for("groups.index"))


def _quota_lock(name: str) -> str:
    """Si la cuota de ese grupo está fijada en config.json o en el entorno (las demás se guardan en el grupo)."""
    if name in runtime().config_entities()["group_quotas"]:
        return _("The quota of the group %(name)s is set in config.json or the environment and cannot be changed "
                 "from the web.", name=repr(name))
    return ""


def _shares_quota(name: str):
    """Cuota de la carpeta personal de los miembros del grupo (MB), o ``""`` si no tiene."""
    value = settings()["storage"].get("group_quotas", {}).get(name)
    return "" if value is None else value


def _save_group_quota(name: str, raw: str | None) -> None:
    """Guarda la cuota del grupo en ``storage.group_quotas`` (vacía = sin cuota de grupo). :class:`GroupError` si
    no es un número o si ese ajuste está fijado en config.json."""
    if raw is None:
        return
    raw = raw.strip()
    if raw and not raw.isdigit():
        raise group_core.GroupError(_("The quota must be a whole number of MB (0 = no quota; empty = none)."))
    current = settings()["storage"].get("group_quotas", {})
    wanted = int(raw) if raw else None
    if current.get(name) == wanted:
        return
    base = runtime_view(settings())
    new = runtime_view(settings())
    quotas = dict(new["storage"].get("group_quotas") or {})
    if wanted is None:
        quotas.pop(name, None)
    else:
        quotas[name] = wanted
    new["storage"]["group_quotas"] = quotas
    try:
        runtime().save(get_db(), new, g.user["username"], strict=True, base=base)
    except ConfigError as exc:
        raise group_core.GroupError(str(exc)) from exc
    invalidate_settings()


def _sync_from_directory(group):
    """Grupo de un proveedor que su directorio conoce: se le ponen su nombre y descripción de allí. Devuelve
    (grupo al día, si vienen del directorio)."""
    if group["builtin"] or not group["external_id"] or group["source"] == group_core.LOCAL:
        return group, False
    info = directory_details([group["external_id"]], group["source"])
    if not info:
        return group, False
    group_core.refresh_details(get_db(), group["source"], info)
    return repo.get_by_id(get_db(), group["id"]), True


@bp.route("/<group_uid>", methods=["GET", "POST"])
@admin_required
def edit(group_uid: str):
    group, from_directory = _sync_from_directory(_get_group(group_uid))
    form = dict(group)
    if request.method == "POST" and group["builtin"]:
        flash(_("This group comes with StorageWeb and cannot be changed."), "error")
        return back(url_for("groups.edit", group_uid=group_uid))
    if request.method == "POST":
        data = _form_data()
        if from_directory and data["source"] == group["source"] and data["external_id"].lower() == group["external_id"]:
            data.update(label=group["label"], description=group["description"])  # los pone el directorio
        try:
            group_core.update_group(get_db(), group, **data)
            _save_group_quota(group["name"], request.form.get("home_quota_mb"))
            if "role" in request.form and group_core.set_role(get_db(), group, request.form.get("role"),
                                                              g.user["username"]):
                _audit("group_role_changed", group["name"], request.form.get("role") or "-")
        except group_core.GroupError as exc:
            flash(exc.message, "error")
            form.update(data)
        else:
            _audit("group_updated", group["name"], f"{data['source']}:{data['external_id']}")
            flash(_("Changes saved."), "info")
            return back(url_for("groups.edit", group_uid=group_uid))
    form["home_quota_mb"] = request.form.get("home_quota_mb", form.get("home_quota_mb")) if request.method == "POST"         else _shares_quota(group["name"])
    return render_template("admin/groups/form.html", group=group, form=form, from_directory=from_directory,
                           quota_lock=_quota_lock(group["name"]),
                           members=group_core.members(get_db(), group),
                           shares=group_core.shares_of(group, _shares()), next="")


@bp.route("/<group_uid>/delete", methods=["POST"])
@admin_required
def delete(group_uid: str):
    group = _get_group(group_uid)
    try:
        group_core.delete_group(get_db(), group)
    except group_core.GroupError as exc:
        flash(exc.message, "error")
        return redirect(url_for("groups.edit", group_uid=group_uid))
    _audit("group_deleted", group["name"])
    try:
        _save_group_quota(group["name"], "")  # su cuota ya no aplica a nadie
    except group_core.GroupError:
        pass  # fijada en config.json: un grupo que no existe no da cuota a nadie
    flash(_("Group «%(name)s» deleted. Users and files have not been touched.", name=group["label"]), "info")
    return redirect(url_for("groups.index"))


@bp.route("/<group_uid>/members", methods=["POST"])
@admin_required
def member_add(group_uid: str):
    group = _get_group(group_uid)
    username = request.form.get("username", "").strip()
    user = users.get_by_username(get_db(), username) if username else None
    if user is None:
        flash(_("The user %(name)s does not exist.", name=repr(username)), "error")
    else:
        group_core.add_member(get_db(), group, user)
        _audit("group_member_added", group["name"], user["username"])
        flash(_("«%(user)s» added to the group «%(group)s».", user=user["username"],
                group=group_core.label(group)), "info")
    return back(url_for("groups.edit", group_uid=group_uid))


@bp.route("/<group_uid>/members/<user_uid>/remove", methods=["POST"])
@admin_required
def member_remove(group_uid: str, user_uid: str):
    group = _get_group(group_uid)
    user = users.get_by_uid(get_db(), user_uid)
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
    return back(url_for("groups.edit", group_uid=group_uid))


# --------------------------------------------------------------------------- vista B

@bp.route("/panel")
@admin_required
def panel_view():
    _remember("panel")
    search = request.args.get("q", "").strip()
    source = request.args.get("source", "")
    source = source if source in group_core.group_sources() else ""
    rows = repo.list_all(get_db(), search=search, source=source or None)
    current = None
    wanted = request.args.get("g")
    for row in rows:
        if row["uid"] == wanted or current is None:
            current = row
            if row["uid"] == wanted:
                break
    tab = request.args.get("tab", "members")
    tab = tab if tab in TABS else "members"
    ctx = {"from_directory": False}
    if current is not None:
        current, from_directory = _sync_from_directory(current)
        ctx = {"from_directory": from_directory, "members": group_core.members(get_db(), current),
               "shares": group_core.shares_of(current, _shares()),
               "form": {**dict(current), "home_quota_mb": _shares_quota(current["name"])},
               "quota_lock": _quota_lock(current["name"])}
    return render_template("admin/groups/panel.html", groups=rows, current=current, tab=tab, search=search,
                           source=source,
                           detected=(detected := group_core.detected(get_db(), _shares())),
                           names=directory_names([d["id"] for d in detected]), **ctx)


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
        base = runtime_view(settings())
        new = runtime_view(settings())
        shares = new["storage"]["shares"]
        changes = []
        for row in rows:
            for share in list(shares):
                value = request.form.get(f"access-{row['uid']}-{share['name']}")
                if value is None or group_core.open_to_everyone(share) or share.get("origin") in ("file", "env"):
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
                runtime().save(get_db(), new, g.user["username"], strict=True, base=base)
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
                           unregistered=unregistered, locked_message="")


search.action("users", _l("New group"), "groups.new", words="crear grupo add create", order=20)


@search.provider("group", _l("Groups"), order=20)
def _search_groups(terms, conn, cfg):
    return [search.item("group", group_core.label(row), row["name"], url_for("groups.edit", group_uid=row["uid"]),
                        icon="users")
            for row in repo.list_all(conn)
            if search.matches(terms, row["name"], group_core.label(row), row["description"], row["external_id"])]

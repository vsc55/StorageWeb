"""Administración de grupos (solo rol admin), con dos vistas para elegir (Personas → Grupos):

* **Lista** (``/admin/groups/list``) + ficha de cada grupo (``/admin/groups/<id>``).
* **Paneles** (``/admin/groups/panel``): lista a la izquierda y detalle con pestañas.

Y la **matriz de accesos** (``/admin/groups/matrix``, en Acceso): acceso de cada grupo a cada
carpeta compartida. No es una vista de grupos, así que ``/admin/groups/`` nunca lleva a ella.

Todas comparten las acciones (alta, clonar, edición, activar o desactivar, miembros, baja); ``next`` decide a dónde
volver. Y **Importar de…** (``/admin/groups/import``): buscar grupos en el directorio de un método (Entra ID) y darlos de
alta, como Personas → Importar.
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, jsonify, make_response, redirect, render_template, request, url_for

from ...core import groups as group_core, named
from ... import providers
from ...core import accounts
from ...db.repositories import users
from ...db.repositories import groups as repo
from ...i18n import _, _l, ngettext
from ...settings import runtime_view
from ..context import get_db, runtime, settings
from ..forms import back, choice, flash_outcome, last_view, pick, use_view
from ..guards import admin_required, audit_event, user_or_404
from .. import search
from .settings.common import save_partial
from ...settings.layers import CONFIG_ORIGINS
from ...text import initials

bp = Blueprint("groups", __name__, url_prefix="/admin/groups")

TABS = ("members", "shares", "link")
STATUS_FILTERS = ("all", "active", "disabled")
SEARCH_LIMIT = 25      # importar: al buscar, lo que empieza por lo escrito
PAGE_SIZE_ALL = 50     # importar: «Mostrar todos», grupos por página (los siguientes, al bajar)
IMPORT_MAX = 200       # importar: «Importar seleccionados», grupos por envío


_audit = audit_event


def _shares() -> list[dict]:
    return settings()["storage"]["shares"]




@bp.app_template_filter("group_label")
def _group_label(group) -> str:
    return group_core.label(group)


@bp.app_template_filter("group_description")
def _group_description(group) -> str:
    return group_core.description(group)


@bp.app_template_filter("group_initials")
def _group_initials(group) -> str:
    """Iniciales para el avatar cuadrado del grupo, de su nombre visible."""
    return initials(group_core.label(group))


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
        found = directory.search(request.args.get("q", "")) or []
        for item in found:  # identificador que se propondría al darlo de alta
            item["suggested_name"] = group_core.suggest_name(get_db(), item.get("name"), item.get("id"))
        return jsonify(groups=found, available=directory.configured())
    abort(404)


def _importers() -> list:
    """Los métodos de los que se pueden importar grupos ahora (el botón «Importar de…»): con directorio de grupos que
    sepa listarlos (Entra ID con Group.Read.All)."""
    cfg = settings()
    return [m for m in providers.methods()
            if m.external_groups and m.enabled(cfg) and (d := m.directory(m.section(cfg))) is not None
            and d.configured()]


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
            "GROUP_SOURCES": group_core.group_sources(), "group_methods": _group_methods,
            "group_importers": _importers}


def _get_group(group_uid: str):
    """El grupo por su identificador público (el de las direcciones); 404 si no existe."""
    group = repo.get_by_uid(get_db(), group_uid)
    if group is None:
        abort(404)
    return group


def _form_data(f=None) -> dict:
    """Los campos del grupo del formulario (o de ``f``: la URL, al venir de «Dar de alta» un grupo detectado)."""
    f = request.form if f is None else f
    return {"label": f.get("label", "").strip(), "description": f.get("description", "").strip(),
            "source": f.get("source", group_core.LOCAL), "external_id": f.get("external_id", "").strip()}


# --------------------------------------------------------------------------- entrada y vista A

@bp.route("/")
@admin_required
def index():
    return redirect(url_for(f"groups.{last_view('groups_view')}_view"))


def _filtered() -> tuple[dict, list]:
    """La búsqueda de Lista y Paneles (``?q=``, ``?source=``, ``?status=``) y los grupos que casan."""
    f = {"q": request.args.get("q", "").strip(), "source": choice("source", group_core.group_sources(), ""),
         "status": choice("status", STATUS_FILTERS, "all")}
    return f, repo.list_all(get_db(), search=f["q"], source=f["source"] or None, status=f["status"])


@bp.route("/list")
@admin_required
def list_view():
    use_view("groups_view", "list")
    filters, rows = _filtered()
    shares = _shares()
    detected = group_core.detected(get_db(), shares)
    return render_template("admin/groups/list.html", groups=rows, filters=filters,
                           shares_by_group={r["id"]: group_core.shares_of(r, shares) for r in rows},
                           detected=detected, names=directory_names(
                               [d["id"] for d in detected] + [r["external_id"] for r in rows if r["external_id"]]))


def _original():
    """El grupo que se clona (``?copy=<uid>``, también al enviar), o ``None``."""
    uid = request.values.get("copy", "")
    return repo.get_by_uid(get_db(), uid) if uid else None


def _after_create(group):
    """A dónde ir tras crear un grupo: desde Paneles, a su ficha en Paneles; si no, a ``next`` o a su ficha."""
    if request.form.get("next", "").startswith(url_for("groups.panel_view")):
        return redirect(url_for("groups.panel_view", g=group["uid"]))
    return back(url_for("groups.edit", group_uid=group["uid"]))


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    """Alta de un grupo; con ``copy``, **Clonar**: el alta rellena con lo del original (nombre «X (copia)», descripción,
    rol y cuota) y la opción de copiar sus miembros y su acceso a carpetas. El clon siempre es local."""
    original = _original()
    form = {**_form_data(request.args), "name": request.args.get("name", ""),
            "source": choice("source", group_core.group_sources(), group_core.LOCAL), "role": "", "home_quota_mb": ""}
    if original is not None:
        label = named.copy_label(group_core.label(original), [r["label"] for r in repo.list_all(get_db())], 200)
        form.update(label=label, name=group_core.suggest_name(get_db(), label), source=group_core.LOCAL,
                    description=group_core.description(original), external_id="",
                    role="" if original["builtin"] else original["role"] or "",
                    home_quota_mb=_shares_quota(original["name"]))
    elif request.method == "GET":
        _fill_from_directory(form)
    if request.method == "POST":
        form = {**_form_data(), "name": request.form.get("name", "").strip(), "role": request.form.get("role", ""),
                "home_quota_mb": request.form.get("home_quota_mb", "")}
        data = {k: form[k] for k in ("name", "label", "description", "source", "external_id")}
        if original is None:
            _fill_from_directory(data)
        try:
            if original is not None:
                gid = group_core.clone_group(get_db(), original, name=data["name"], label=data["label"],
                                             description=data["description"],
                                             members=request.form.get("copy_members") == "1")
            else:
                gid = group_core.create_group(get_db(), **data)
        except group_core.GroupError as exc:
            flash(exc.message, "error")
        else:
            group = repo.get_by_id(get_db(), gid)
            _audit("group_created", group["name"], f"{group['source']}:{group['external_id'] or ''}"
                   + (f" copy={original['name']}" if original is not None else ""))
            _settings_of_new(group, original)
            flash(_("Group «%(name)s» created.", name=group_core.label(group)), "info")
            return _after_create(group)
    return render_template("admin/groups/form.html", group=None, form=form, next=request.values.get("next", ""),
                           from_directory=False, original=original,
                           copy_counts=_copy_counts(original) if original is not None else None)


def _copy_counts(original) -> dict:
    """Lo que se copiaría al clonar: cuántos miembros y a cuántas carpetas da acceso."""
    return {"members": len(group_core.members(get_db(), original)),
            "shares": len(group_core.shares_of(original, _shares()))}


def _settings_of_new(group, original) -> None:
    """Rol, cuota y (al clonar) acceso a carpetas del grupo recién creado: son ajustes, se guardan aparte. Lo que no
    se puede (cuota fijada en config.json, carpeta de config.json…) se avisa sin deshacer el alta."""
    try:
        if request.form.get("role") and group_core.set_role(get_db(), group, request.form.get("role"),
                                                            g.user["username"]):
            _audit("group_role_changed", group["name"], request.form.get("role"))
        _save_group_quota(group["name"], request.form.get("home_quota_mb"))
    except group_core.GroupError as exc:
        flash(exc.message, "error")
    if original is None or request.form.get("copy_access") != "1":
        return
    shares = runtime_view(settings())["storage"]["shares"]
    copied, skipped = [], []
    for share in group_core.shares_of(original, _shares()):
        if share.get("origin") in CONFIG_ORIGINS:
            skipped.append(share["label"])
            continue
        shares = group_core.apply_access(shares, group, share["name"], share["level"])
        copied.append(f"{group['name']}@{share['name']}={share['level']}")
    if copied:
        _draft, error = save_partial(lambda: {"storage": {"shares": shares}}, strict=True)
        if error:
            flash(_("The access to shared folders was not copied: %(error)s", error=error), "error")
        else:
            _audit("group_access_updated", None, ", ".join(copied)[:500])
    if skipped:
        flash(_("Shared folders set in config.json are not changed from the web: give access to the new group "
                "there (%(shares)s).", shares=", ".join(skipped)), "error")


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
    flash_outcome(ngettext("Group registered: %(names)s.", "%(num)s groups registered: %(names)s.", len(created),
                           names=", ".join(created)) if created else None, errors)
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
    quotas = dict(runtime_view(settings())["storage"].get("group_quotas") or {})
    if wanted is None:
        quotas.pop(name, None)
    else:
        quotas[name] = wanted
    _draft, error = save_partial(lambda: {"storage": {"group_quotas": quotas}}, strict=True)
    if error:
        raise group_core.GroupError(str(error)) from error


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


@bp.route("/<group_uid>/status", methods=["POST"])
@admin_required
def set_status(group_uid: str):
    """Activar o desactivar (``enabled`` = 1 o 0). Desactivado se conserva entero, pero no da nada a sus miembros."""
    group = _get_group(group_uid)
    enabled = request.form.get("enabled") == "1"
    try:
        changed = group_core.set_enabled(get_db(), group, enabled)
    except group_core.GroupError as exc:
        flash(exc.message, "error")
    else:
        if changed:
            _audit("group_enabled" if enabled else "group_disabled", group["name"])
            flash(_("Group «%(name)s» enabled.", name=group_core.label(group)) if enabled else
                  _("Group «%(name)s» disabled: its members no longer get its shared folders, role or quota.",
                    name=group_core.label(group)), "info")
    return back(url_for("groups.edit", group_uid=group_uid))


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
    user = user_or_404(user_uid)
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
    use_view("groups_view", "panel")
    filters, rows = _filtered()
    current = pick(rows, request.args.get("g"))
    tab = choice("tab", TABS, "members")
    ctx = {"from_directory": False}
    if current is not None:
        current, from_directory = _sync_from_directory(current)
        ctx = {"from_directory": from_directory, "members": group_core.members(get_db(), current),
               "shares": group_core.shares_of(current, _shares()),
               "form": {**dict(current), "home_quota_mb": _shares_quota(current["name"])},
               "quota_lock": _quota_lock(current["name"])}
    return render_template("admin/groups/panel.html", groups=rows, current=current, tab=tab, filters=filters,
                           detected=(detected := group_core.detected(get_db(), _shares())),
                           names=directory_names([d["id"] for d in detected]), **ctx)


# --------------------------------------------------------------------------- importar de un directorio

@bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_view():
    """Buscar grupos en el directorio de un método (Entra ID) y darlos de alta: el nombre y la descripción de allí y
    un identificador sacado del nombre, como «Dar de alta» un grupo detectado. Lo que manda el navegador es solo el
    identificador del grupo, que se vuelve a leer del directorio."""
    methods = _importers()
    if not methods:
        flash(_("No sign-in method can import groups now (for Microsoft Entra ID: enabled, with the client secret "
                "and the Group.Read.All permission)."), "error")
        return redirect(url_for("groups.index"))
    key = request.values.get("source") or methods[0].key
    method = next((m for m in methods if m.key == key), methods[0])
    directory = method.directory(method.section(settings()))
    query = request.values.get("q", "").strip()[:100]
    show_all = request.values.get("all") == "1" and not query
    if request.method == "POST":
        single = request.form.get("external_id", "")
        wanted = [single] if single else list(dict.fromkeys(request.form.getlist("ids")))[:IMPORT_MAX]
        infos = directory.details([w.lower() for w in wanted]) if wanted else {}
        created, errors = [], []
        for external_id in wanted:
            info = infos.get(external_id.lower())
            if info is None:
                errors.append(_("The group %(id)s is not in the directory.", id=external_id))
                continue
            try:
                gid = group_core.register_external(get_db(), source=method.key, external_id=external_id, info=info)
            except group_core.GroupError as exc:
                errors.append(f"{info['name']}: {exc.message}")
                continue
            group = repo.get_by_id(get_db(), gid)
            _audit("group_created", group["name"], f"{group['source']}:{group['external_id'] or ''} import")
            created.append(group_core.label(group))
        flash_outcome(ngettext("Group registered: %(names)s.", "%(num)s groups registered: %(names)s.", len(created),
                               names=", ".join(created)) if created else None, errors)
        if not wanted:
            flash(_("Select at least one group."), "error")
        return redirect(url_for("groups.import_view", source=method.key, q=query or None,
                                all="1" if request.form.get("all") == "1" else None))
    found, following = None, ""
    if show_all:
        page = directory.list(request.args.get("cursor", "")[:4096], PAGE_SIZE_ALL)
        found, following = page if page is not None else (None, "")
    elif len(query) >= 2:
        found = directory.search(query, SEARCH_LIMIT)
    rows = [{"group": item, "imported": repo.get_by_external(get_db(), method.key, item["id"])}
            for item in found or []]
    more = url_for("groups.import_view", source=method.key, all="1", cursor=following, rows="1") if following else ""
    context = {"methods": methods, "method": method, "query": query, "rows": rows, "show_all": show_all,
               "failed": (show_all or len(query) >= 2) and found is None, "limit": SEARCH_LIMIT, "more": more}
    if request.args.get("rows") == "1":
        # Solo las filas de la página siguiente (al bajar); la dirección de la otra, en X-Next
        resp = make_response(render_template("admin/groups/_import_rows.html", **context))
        resp.headers["X-Next"] = more
        return resp
    if request.args.get("partial") == "1":
        # Solo los resultados: la búsqueda mientras se escribe (admin/directory-import.js)
        return render_template("admin/groups/_import_results.html", **context)
    return render_template("admin/groups/import.html", **context)


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
        shares = runtime_view(settings())["storage"]["shares"]
        changes = []
        for row in rows:
            for share in list(shares):
                value = request.form.get(f"access-{row['uid']}-{share['name']}")
                if value is None or group_core.open_to_everyone(share) or share.get("origin") in CONFIG_ORIGINS:
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
            _draft, error = save_partial(lambda: {"storage": {"shares": shares}}, strict=True)
            if error:
                flash(_("The changes were not saved: %(error)s", error=error), "error")
                return redirect(url_for("groups.matrix_view"))
            _audit("group_access_updated", None, ", ".join(changes)[:500])
            flash(_("Access saved: %(count)s changes.", count=len(changes)), "info")
        else:
            flash(_("There were no changes."), "info")
        return redirect(url_for("groups.matrix_view"))
    shares = _shares()
    names = group_core.refs(rows)
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

"""Usuarios: lista y paneles, ficha, acciones en bloque y edición."""
from __future__ import annotations

import re

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from ....core import accounts, mfa
from ....core import groups as group_core
from ....core.permissions import ADMIN, PERMISSION_LABELS, permissions_for
from ....core import quota
from ....core.storage import available_roots, explain_access, home_quota_mb
from ....db.repositories import api_tokens, audit, users
from ....db.repositories import mfa as mfa_repo
from ....db.repositories import groups as group_repo
from ....db.repositories import sessions as session_repo
from ....i18n import _, _l, format_size, ngettext
from ....settings import PERMISSIONS, ROLES
from ...context import get_db, settings
from ...forms import back, split_list
from ...guards import admin_required, audit_event, safe_next
from ... import search
from . import bp


# --------------------------------------------------------------------------- usuarios

USER_STATUS_FILTERS = ("all", "active", "disabled")
USER_VIEWS = ("list", "panel")
USER_TABS = ("profile", "groups", "access", "activity")
PAGE_SIZE = 25
BULK_ACTIONS = ("disable", "enable", "role_user", "role_admin", "add_group")


@bp.app_template_filter("initials")
def _initials(user) -> str:
    """Iniciales para el avatar: de su nombre visible o, si no tiene, de su usuario."""
    name = (user["display_name"] or user["username"].split("@")[0]).strip()
    parts = [p for p in re.split(r"[\s._-]+", name) if p]
    return ("".join(p[0] for p in parts[:2]) if len(parts) > 1 else name[:2]).upper()


def _user_filters() -> dict:
    a = request.args
    status = a.get("status", "all")
    source = a.get("source", "")
    role = a.get("role", "")
    return {"q": a.get("q", "").strip(),
            "status": status if status in USER_STATUS_FILTERS else "all",
            "source": source if source in accounts.sources() else "",
            "role": role if role in ROLES else "",
            "group": a.get("group", "")}  # identificador público del grupo


def _filtered_users(f: dict) -> list:
    group = group_repo.get_by_uid(get_db(), f["group"]) if f["group"] else None
    return users.list_all(get_db(), search=f["q"], status=None if f["status"] == "all" else f["status"],
                          source=f["source"] or None, role=f["role"] or None,
                          group_id=group["id"] if group else (-1 if f["group"] else None))


def _user_or_404(user_uid: str):
    """La cuenta por su identificador público (el de las direcciones); 404 si no existe."""
    user = users.get_by_uid(get_db(), user_uid)
    if user is None:
        abort(404)
    return user


def _group_names(user_rows) -> dict:
    """Nombre visible de los grupos de cada usuario (para la lista y las tarjetas)."""
    result = {}
    for u in user_rows:
        result[u["id"]] = [group_core.label(m) for m in group_core.memberships(get_db(), u)]
    return result


@bp.route("/users/")
@admin_required
def users_index():
    view = session.get("users_view")
    return redirect(url_for("admin.users_panel" if view == "panel" else "admin.users_list"))


@bp.route("/users")
@admin_required
def users_list():
    session["users_view"] = "list"
    f = _user_filters()
    rows = _filtered_users(f)
    page = max(request.args.get("page", 1, type=int), 1)
    pages = max((len(rows) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(page, pages)
    shown = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    return render_template("admin/users.html", users=shown, total=len(rows), page=page, pages=pages,
                           session_count=len(session_repo.list_all(get_db())),
                           filters=f, search=f["q"], status=f["status"], counts=users.counts(get_db()),
                           all_groups=group_repo.list_all(get_db()), group_names=_group_names(shown),
                           page_size=PAGE_SIZE, mfa_users=mfa_repo.enrolled_ids(get_db()))


@bp.route("/users/bulk", methods=["POST"])
@admin_required
def users_bulk():
    """Acción sobre varios usuarios. Se aplica a cada uno con sus protecciones; los errores se listan."""
    action = request.form.get("action", "")
    ids = [row["id"] for row in (users.get_by_uid(get_db(), x) for x in request.form.getlist("ids")) if row]
    if action not in BULK_ACTIONS or not ids:
        flash(_("Select some users and an action."), "error")
        return back(url_for("admin.users_list"))
    group = None
    if action == "add_group":
        group = group_repo.get_by_uid(get_db(), request.form.get("group_uid", ""))
        if group is None:
            flash(_("Choose the group."), "error")
            return back(url_for("admin.users_list"))
    done, errors = 0, []
    for uid in ids:
        user = users.get_by_id(get_db(), uid)
        if user is None:
            continue
        try:
            if action in ("disable", "enable"):
                accounts.set_enabled(get_db(), user, g.user, action == "enable")
                audit_event("user_enabled" if action == "enable" else "user_disabled", user["username"], user["source"])
            elif action in ("role_user", "role_admin"):
                role = ADMIN if action == "role_admin" else "user"
                accounts.set_role(get_db(), user, g.user, role)
                audit_event("user_updated", user["username"], f"role={role}")
            else:
                group_core.add_member(get_db(), group, user)
                audit_event("group_member_added", group["name"], user["username"])
        except accounts.AccountError as exc:
            errors.append(f"{user['username']}: {exc.message}")
        else:
            done += 1
    if done:
        flash(ngettext("Done for %(num)s user.", "Done for %(num)s users.", done), "info")
    for error in errors:
        flash(error, "error")
    return back(url_for("admin.users_list"))


def _user_detail(user) -> dict:
    """Lo común de la ficha (A), los paneles (B) y la edición rápida (C)."""
    cfg = settings()
    labels = {}
    for grp in group_repo.list_all(get_db()):
        labels[grp["name"]] = group_core.label(grp)
        if grp["external_id"]:
            labels[grp["external_id"]] = group_core.label(grp)
    perms = permissions_for(user, cfg)
    home = available_roots(user, cfg)[0]
    used, complete = quota.usage(home)
    return {**_user_groups_context(user),
            "home_usage": {"used": format_size(used), "complete": complete}, "home_quota": quota.status(home),
            # La que tendría sin una propia: la de sus grupos o la de por defecto
            "default_quota_mb": home_quota_mb({**dict(user), "quota_mb": None}, cfg),
            "user_sessions": session_repo.list_all(get_db(), user["id"]),
            "user_tokens": api_tokens.list_for_user(get_db(), user["id"]),
            "access": explain_access(user, cfg, labels) if user["enabled"] else [],
            "activity": audit.for_user(get_db(), user["username"], 8),
            "mfa": mfa.status(get_db(), user), "mfa_applies": mfa.applies(user),
            "mfa_required": mfa.required(cfg, user),
            "role_permissions": [PERMISSION_LABELS[p] for p in PERMISSIONS if p in perms]}


def _pick(rows, wanted: str | None):
    for row in rows:
        if row["uid"] == wanted:
            return row
    return rows[0] if rows else None


@bp.route("/users/panel")
@admin_required
def users_panel():
    session["users_view"] = "panel"
    f = _user_filters()
    rows = _filtered_users(f)
    current = _pick(rows, request.args.get("u"))
    tab = request.args.get("tab", "profile")
    tab = tab if tab in USER_TABS else "profile"
    ctx = {}
    if current is not None:
        ctx = {**_user_detail(current), "form": {**dict(current), "enabled": bool(current["enabled"])}}
    return render_template("admin/users/panel.html", users=rows, current=current, tab=tab, filters=f,
                           counts=users.counts(get_db()), **ctx)


@bp.route("/users/<user_uid>/status", methods=["POST"])
@admin_required
def user_status(user_uid: str):
    """Activa o desactiva una cuenta (también de Entra ID o PAM: desactivar bloquea el acceso)."""
    user = _user_or_404(user_uid)
    enabled = request.form.get("enabled") == "1"
    try:
        accounts.set_enabled(get_db(), user, g.user, enabled)
    except accounts.AccountError as exc:
        flash(exc.message, "error")
    else:
        audit_event("user_enabled" if enabled else "user_disabled", user["username"], user["source"])
        message = _("User «%(name)s» enabled.", name=user["username"]) if enabled else \
            _("User «%(name)s» disabled: they can no longer sign in.", name=user["username"])
        flash(message, "info")
    return back(url_for("admin.user_edit", user_uid=user_uid))


@bp.route("/users/<user_uid>/mfa/reset", methods=["POST"])
@admin_required
def user_mfa_reset(user_uid: str):
    """Quita la verificación en dos pasos de otra cuenta: el camino de vuelta para quien perdió el móvil y los códigos.
    No existe lo contrario: nadie puede activar la de otro (solo el dueño da de alta la aplicación que tiene en la
    mano). La propia se quita desde Mi perfil, con un código."""
    user = _user_or_404(user_uid)
    if user["id"] == g.user["id"]:
        flash(_("Turn off your own two-step verification in My profile."), "error")
    elif mfa.disable(get_db(), user):
        audit_event("mfa_reset_by_admin", user["username"])
        flash(_("Two-step verification removed from «%(name)s». On their next sign-in they will only need their "
                "password, or will set it up again if it is required.", name=user["username"]), "info")
    return back(url_for("admin.user_edit", user_uid=user_uid))


def _user_form_data() -> dict:
    f = request.form
    return {
        "display_name": f.get("display_name", "").strip(),
        "email": f.get("email", "").strip(),
        "role": f.get("role", "user"),
        "home_path": f.get("home_path", "").strip(),
        "enabled": f.get("enabled") == "on",
        **_quota_field(f),
    }


def _quota_field(f) -> dict:
    """La cuota del formulario, solo si viene (vacía = la de por defecto; un valor no válido lo rechaza
    ``accounts.update_account``)."""
    if "quota_mb" not in f:
        return {}
    raw = f.get("quota_mb", "").strip()
    if not raw:
        return {"quota_mb": None}
    return {"quota_mb": int(raw) if raw.isdigit() else -1}


@bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_new():
    form = {"source": accounts.default_source(), "role": "user", "enabled": True}
    if request.method == "POST":
        form = {**_user_form_data(), "username": request.form.get("username", "").strip(),
                "password": request.form.get("password", ""),
                "source": request.form.get("source", accounts.default_source()), "groups": split_list(request.form.get("groups", ""))}
        try:
            form.pop("quota_mb", None)
            uid = accounts.create_account(get_db(), 
                username=form["username"], source=form["source"], role=form["role"],
                password=form["password"], display_name=form["display_name"], email=form["email"],
                groups=form["groups"], home_path=form["home_path"], enabled=form["enabled"])
        except accounts.AccountError as exc:
            flash(exc.message, "error")
        else:
            audit_event("user_created", form["username"], f"{form['source']}:{form['role']}")
            flash(_("User «%(name)s» created.", name=form["username"]), "info")
            return redirect(url_for("admin.user_edit", user_uid=users.get_by_id(get_db(), uid)["uid"]))
        form.pop("password", None)
    return render_template("admin/user_form.html", user=None, form=form, sources=accounts.sources())


@bp.route("/users/<user_uid>", methods=["GET", "POST"])
@admin_required
def user_edit(user_uid: str):
    user = _user_or_404(user_uid)
    form = {**dict(user), "enabled": bool(user["enabled"])}
    if request.method == "POST":
        # Activar o desactivar no es «editar»: tiene su botón (admin.user_status), con su confirmación y sus
        # reglas. Aquí se conserva como está, venga lo que venga en el formulario
        data = {**_user_form_data(), "enabled": bool(user["enabled"])}
        try:
            accounts.update_account(get_db(), user, g.user, **data)
        except accounts.AccountError as exc:
            flash(exc.message, "error")
            form.update(data)
        else:
            detail = f"role={data['role']} enabled={data['enabled']}"
            audit_event("user_updated", user["username"], detail)
            flash(_("Changes saved."), "info")
            return back(url_for("admin.user_edit", user_uid=user_uid))
        if request.form.get("next"):
            return back(url_for("admin.user_edit", user_uid=user_uid))
    return render_template("admin/user_form.html", user=user, form=form, sources=accounts.sources(),
                           **_user_detail(user))


@bp.route("/users/<user_uid>/password", methods=["GET", "POST"])
@admin_required
def user_password(user_uid: str):
    """Poner una contraseña nueva a otra cuenta (la olvidó, o se sospecha que otro la sabe). La propia se cambia en Mi
    perfil, que pide la actual.

    Cierra sus sesiones, pero sus tokens de API siguen valiendo (la extensión de VS Code o la unidad de red no se
    desconectan por un olvido). Para cortarle el paso del todo está Desactivar, o revocar sus tokens en la ficha."""
    user = _user_or_404(user_uid)
    done_url = back(url_for("admin.user_edit", user_uid=user_uid))
    # Se comprueba aquí (y otra vez en accounts.set_password), no se da por bueno que el botón estuviera
    # desactivado: un POST a mano sobre la propia cuenta o una de SSO es un 403 y queda en la auditoría
    if user["id"] == g.user["id"]:
        if request.method == "POST":
            abort(403, description=_("Change your own password in My profile, with the current one."))
        return redirect(url_for("profile.section", section="security") + "#password")
    if not accounts.stores_password(user["source"]):
        abort(403, description=_("Only local users have a password that can be changed."))
    if request.method == "POST":
        new = request.form.get("password", "")
        if new != request.form.get("repeat_password", ""):
            flash(_("The new passwords do not match."), "error")
        else:
            try:
                closed = accounts.set_password(get_db(), user, g.user, new)
            except accounts.AccountError as exc:
                flash(exc.message, "error")
            else:
                audit_event("password_reset_by_admin", user["username"], f"sessions_closed={closed}")
                flash(_("New password for «%(name)s». Their open sessions have been closed.", name=user["username"]),
                      "info")
                return done_url
    # «Volver» y «Cancelar» llevan a ``next``: solo una ruta de este sitio (si no, un enlace con
    # ?next=https://otro.sitio sacaría al administrador de aquí). Uno que no lo es se ignora: vuelve a la ficha
    nxt = request.values.get("next") or ""
    return render_template("admin/user_password.html", user=user,
                           next_url=nxt if nxt and safe_next(nxt) == nxt else "")


def _user_groups_context(user) -> dict:
    """Grupos del usuario (con origen), grupos a los que se puede añadir y grupos del proveedor sin alta."""
    rows = group_core.memberships(get_db(), user)
    mine = {g["id"] for g in rows}
    names = {g["name"] for g in rows} | {g["external_id"] for g in rows if g["external_id"]}
    known = {g["name"] for g in group_repo.list_all(get_db())} | \
        {g["external_id"] for g in group_repo.list_all(get_db()) if g["external_id"]}
    unknown = sorted(group_core.split(user["external_groups"]) - names - known)
    from ..groups import directory_names
    return {"memberships": rows, "unknown_groups": unknown,
            "unknown_names": directory_names(unknown, user["source"]),
            "addable_groups": [g for g in group_repo.list_all(get_db()) if g["id"] not in mine]}


@bp.route("/users/<user_uid>/groups", methods=["POST"])
@admin_required
def user_group_add(user_uid: str):
    user = users.get_by_uid(get_db(), user_uid)
    group = group_repo.get_by_uid(get_db(), request.form.get("group_uid", ""))
    if user is None or group is None:
        abort(404)
    group_core.add_member(get_db(), group, user)
    audit_event("group_member_added", group["name"], user["username"])
    flash(_("«%(user)s» added to the group «%(group)s».", user=user["username"],
            group=group_core.label(group)), "info")
    return back(url_for("admin.user_edit", user_uid=user_uid))


@bp.route("/users/<user_uid>/delete", methods=["POST"])
@admin_required
def user_delete(user_uid: str):
    user = _user_or_404(user_uid)
    try:
        accounts.delete_account(get_db(), user, g.user)
    except accounts.AccountError as exc:
        flash(exc.message, "error")
        return redirect(url_for("admin.user_edit", user_uid=user_uid))
    audit_event("user_deleted", user["username"])
    flash(_("User «%(name)s» deleted (their files have not been removed).", name=user["username"]), "info")
    return redirect(url_for("admin.users_list"))


search.action("user", _l("New user"), "admin.user_new", words="alta crear usuario cuenta add create", order=10)


@search.provider("user", _l("Users"), order=10)
def _search_users(terms, conn, cfg):
    # Se filtra aquí y no en SQL para no distinguir tildes (LIKE sí las distingue)
    return [search.item("user", row["display_name"] or row["username"], f"{row['username']} · {row['source']}",
                        url_for("admin.user_edit", user_uid=row["uid"]), "" if row["enabled"] else _("Disabled"),
                        "user")
            for row in users.list_all(conn) if search.matches(terms, row["username"], row["display_name"],
                                                              row["email"])]

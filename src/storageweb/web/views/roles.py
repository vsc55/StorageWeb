"""Acceso → Roles (``core/roles.py``): la lista de roles en dos vistas, **Lista** (una tabla) y **Paneles** (la lista a
la izquierda y la ficha del elegido a la derecha), con el mismo diseño que Personas → Usuarios y Grupos: cabecera
con la vista, *Nuevo rol* y la búsqueda debajo. La última vista se recuerda en la sesión (``roles_view``).

Aquí también la ficha de cada rol: crear, editar y borrar los propios; los permisos del de serie Usuario (el ajuste
``permissions.user``, con sus bloqueos de config.json/entorno) y «Usar para las cuentas nuevas»
(``permissions.default_role``). Administrador y Sin permisos no se editan."""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ...core import roles
from ...core.permissions import ADMIN, PERMISSION_LABELS, ROLE_LABELS, USER, default_role
from ...i18n import _, ngettext
from ...settings import PERMISSIONS
from ...text import fold
from ..context import get_db, runtime, settings
from ..forms import back, choice, last_view, pick, use_view
from ..guards import admin_required, audit_event

bp = Blueprint("roles", __name__, url_prefix="/admin/access/roles")

KINDS = ("builtin", "custom")


def _list_url(r: str | None = None):
    """La lista de roles en la vista en la que estaba (Lista o Paneles, con el rol ``r`` elegido)."""
    if last_view("roles_view") == "panel":
        return url_for("roles.panel_view", r=r)
    return url_for("roles.list_view")


def _user_role() -> dict:
    return {"key": USER, "label": str(ROLE_LABELS[USER]), "description": "", "builtin": True}


def _locked(role: dict | None) -> set[str]:
    """Los permisos de Usuario fijados en config.json o el entorno (no se cambian desde la web)."""
    if not (role and role.get("builtin")):
        return set()
    return {p for p in PERMISSIONS if runtime().lock_of(f"permissions.user.{p}")}


def _render(role: dict | None, form: dict, status: int = 200):
    builtin = bool(role and role.get("builtin"))
    usage = roles.usage(get_db(), role["key"]) if role and not builtin else {"users": [], "groups": []}
    return render_template("admin/roles/form.html", role=role, form=form, usage=usage, permissions=PERMISSIONS,
                           PERMISSION_LABELS=PERMISSION_LABELS, locked=_locked(role)), status


def _filters() -> dict:
    return {"q": request.args.get("q", "").strip(), "kind": choice("kind", KINDS, "")}


def _filtered(all_roles: list[dict], f: dict) -> list[dict]:
    """Los que casan con la búsqueda (sin mayúsculas ni tildes) y el tipo, por orden alfabético en las dos vistas."""
    q = fold(f["q"])
    found = [r for r in all_roles
             if (not q or q in fold(r["label"]) or q in fold(r["description"] or "") or q in r["key"])
             and (not f["kind"] or (f["kind"] == "builtin") == r["builtin"])]
    return sorted(found, key=lambda r: fold(r["label"]))


def _common(cfg: dict, all_roles: list[dict], f: dict) -> dict:
    return {"filters": f, "default_key": default_role(cfg), "PERMISSION_LABELS": PERMISSION_LABELS,
            "permissions": PERMISSIONS, "default_locked": bool(runtime().lock_of("permissions.default_role")),
            "counts": {"all": len(all_roles), "custom": sum(1 for r in all_roles if not r["builtin"])}}


@bp.route("/")
@admin_required
def index():
    return redirect(_list_url())


@bp.route("/list")
@admin_required
def list_view():
    use_view("roles_view", "list")
    cfg = settings()
    all_roles = roles.all_roles(get_db(), cfg)
    f = _filters()
    return render_template("admin/roles/list.html", roles_list=_filtered(all_roles, f), **_common(cfg, all_roles, f))


def _tabs(role: dict) -> list[tuple[str, str]]:
    """Las pestañas de la ficha en Paneles, como las de Usuarios: *General* (nombre y descripción, solo los propios),
    *Permisos* y *Quién lo tiene*."""
    tabs = [] if role["builtin"] else [("general", _("General"))]
    perms = len(PERMISSIONS) if role["key"] == ADMIN else len(role["permissions"])
    tabs.append(("permissions", _("Permissions (%(count)s)", count=perms)))
    tabs.append(("members", _("Who has it (%(count)s)", count=role["users"] + role["groups"])))
    return tabs


@bp.route("/panel")
@admin_required
def panel_view():
    """Vista Paneles: los roles a la izquierda y la ficha del elegido (``?r=``) a la derecha, en pestañas
    (``?tab=``)."""
    use_view("roles_view", "panel")
    cfg = settings()
    all_roles = roles.all_roles(get_db(), cfg)
    f = _filters()
    shown = _filtered(all_roles, f)
    current = pick(shown, request.args.get("r"), key="key")
    form, usage, tabs, tab = {}, {"users": [], "groups": []}, [], ""
    if current is not None:
        tabs = _tabs(current)
        tab = choice("tab", dict(tabs), tabs[0][0])
        usage = roles.usage(get_db(), current["key"])
        if current["key"] == ADMIN:
            form = {"permissions": list(PERMISSIONS)}
        elif current["key"] == USER:
            form = {"permissions": [p for p in PERMISSIONS if cfg["permissions"]["user"].get(p)]}
        else:
            form = {"label": current["label"], "description": current["description"],
                    "permissions": current["permissions"]}
    return render_template("admin/roles/panel.html", roles_list=shown, current=current, form=form, usage=usage,
                           tabs=tabs, tab=tab, locked=_locked(current), **_common(cfg, all_roles, f))


@bp.route("/<key>/default", methods=["POST"])
@admin_required
def make_default(key: str):
    """La estrella: ``permissions.default_role`` = este rol (cualquiera, también Administrador: la página lo confirma
    antes y *Estado de la seguridad* lo avisa)."""
    from .settings.common import save_partial  # noqa: PLC0415
    if not roles.exists(get_db(), key):
        abort(404)
    _draft, error = save_partial(lambda: {"permissions": {"default_role": key}}, strict=True)
    if error:
        flash(str(error), "error")
    else:
        audit_event("settings_updated", None, "permissions")
        flash(_("New accounts will get the role «%(name)s».", name=roles.label_of(settings(), key)), "info")
    return back(_list_url())


def _edit_user():
    """La ficha del rol de serie Usuario: solo sus permisos (``permissions.user``); los bloqueados por config.json o
    el entorno no se pueden cambiar (el navegador no envía los desactivados y ``save`` los descarta)."""
    from .settings.common import save_partial  # noqa: PLC0415
    role = _user_role()
    current = settings()["permissions"]["user"]
    form = {"permissions": [p for p in PERMISSIONS if current.get(p)]}
    if request.method == "POST":
        wanted = set(_form()["permissions"])
        _draft, error = save_partial(lambda: {"permissions": {"user": {p: p in wanted for p in PERMISSIONS}}})
        if error:
            flash(str(error), "error")
            return _render(role, {"permissions": sorted(wanted, key=PERMISSIONS.index)}, 400)
        now = settings()["permissions"]["user"]
        audit_event("role_updated", USER, ",".join(p for p in PERMISSIONS if now.get(p)))
        flash(_("Changes saved."), "info")
        return back(_list_url(r=USER))
    return _render(role, form)


def _form(base: dict | None = None) -> dict:
    """Lo enviado. Las pestañas de Paneles envían solo su parte (``part`` = ``general`` o ``permissions``): lo demás
    se queda como está en ``base``."""
    f = request.form
    out = {"label": f.get("label", "").strip(), "description": f.get("description", "").strip(),
           "permissions": [p for p in f.getlist("permissions") if p in PERMISSIONS]}
    part = f.get("part")
    if base and part == "general":
        out["permissions"] = list(base["permissions"])
    elif base and part == "permissions":
        out["label"], out["description"] = base["label"], base["description"] or ""
    return out


@bp.route("/new", methods=["GET", "POST"])
@admin_required
def new():
    """Nuevo rol. Con ``?copy=<clave>`` (*Clonar*) sale relleno con lo de ese rol y el nombre «X (copia)»."""
    form = {"label": "", "description": "", "permissions": ["download"]}
    if request.method == "GET" and request.args.get("copy"):
        form = roles.copy_of(get_db(), settings(), request.args["copy"])
        if form is None:
            abort(404)
    if request.method == "POST":
        form = _form()
        try:
            key = roles.create(get_db(), form["label"], form["description"], form["permissions"],
                               username=g.user["username"])
        except roles.RoleError as exc:
            flash(exc.message, "error")
            return _render(None, form, 400)
        audit_event("role_created", key, ",".join(form["permissions"]))
        flash(_("Role «%(name)s» created. Give it to people in their record or to a group.", name=form["label"]), "info")
        return redirect(_list_url(r=key))       # a la lista, en la vista en la que estaba (en Paneles, ya elegido)
    return _render(None, form)


@bp.route("/<key>", methods=["GET", "POST"])
@admin_required
def edit(key: str):
    if key == USER:
        return _edit_user()
    role = roles.get(get_db(), key)
    if role is None:
        abort(404)
    form = dict(role)
    if request.method == "POST":
        form = _form(role)
        try:
            roles.update(get_db(), key, form["label"], form["description"], form["permissions"],
                         username=g.user["username"])
        except roles.RoleError as exc:
            flash(exc.message, "error")
            return _render(role, form, 400)
        audit_event("role_updated", key, ",".join(form["permissions"]))
        flash(_("Changes saved."), "info")
        return back(_list_url(r=key))
    return _render(role, form)


@bp.route("/<key>/delete", methods=["POST"])
@admin_required
def delete(key: str):
    role = roles.get(get_db(), key)
    if role is None:
        abort(404)
    moved = roles.delete(get_db(), key, username=g.user["username"])
    audit_event("role_deleted", key, f"users={moved['users']} groups={moved['groups']}")
    flash(_("Role «%(name)s» deleted.", name=role["label"]) + (
        " " + ngettext("%(num)s person now has no permissions.", "%(num)s people now have no permissions.",
                       moved["users"]) if moved["users"] else ""), "info")
    return redirect(_list_url())

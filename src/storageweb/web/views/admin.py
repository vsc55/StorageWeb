"""Administración web (solo rol admin): usuarios, ajustes y auditoría."""
from __future__ import annotations

import json
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from ...core import accounts
from ...core import groups as group_core
from ...core.permissions import ADMIN, PERMISSION_LABELS, ROLE_LABELS, permissions_for
from ...core.storage import explain_access
from ...db.repositories import audit, users
from ...db.repositories import groups as group_repo
from ...i18n import LOCALES, _, locale_display_name, ngettext
from ...providers import SSO_PROVIDERS
from ...settings import DEFAULTS, PERMISSIONS, ROLES, ConfigError, deep_merge, mask_secrets, runtime_view
from ..context import boot_config, get_db, invalidate_settings, runtime, settings
from ..guards import admin_required, client_ip, safe_next

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _audit(action: str, target: str | None = None, detail: str | None = None) -> None:
    audit.log(get_db(), action, target, username=g.user["username"], ip=client_ip(), detail=detail)


def _split(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n]", value or "") if x.strip()]


@bp.context_processor
def _labels():
    return {"ROLE_LABELS": ROLE_LABELS, "SOURCE_LABELS": accounts.SOURCE_LABELS,
            "PERMISSION_LABELS": PERMISSION_LABELS, "ROLES": ROLES}


@bp.route("/")
@admin_required
def index():
    return redirect(url_for("admin.users_list"))


# --------------------------------------------------------------------------- usuarios

USER_STATUS_FILTERS = ("all", "active", "disabled")
USER_VIEWS = ("list", "panel", "cards")
USER_TABS = ("profile", "groups", "access", "activity")
PAGE_SIZE = 25
BULK_ACTIONS = ("disable", "enable", "role_user", "role_admin", "add_group")


@bp.app_template_filter("initials")
def _initials(user) -> str:
    """Iniciales para el avatar: de su nombre visible o, si no tiene, de su usuario."""
    name = (user["display_name"] or user["username"].split("@")[0]).strip()
    parts = [p for p in re.split(r"[\s._-]+", name) if p]
    return ("".join(p[0] for p in parts[:2]) if len(parts) > 1 else name[:2]).upper()


def _back(default: str):
    target = request.form.get("next") or request.args.get("next")
    return redirect(safe_next(target) if target else default)


def _user_filters() -> dict:
    a = request.args
    status = a.get("status", "all")
    source = a.get("source", "")
    role = a.get("role", "")
    return {"q": a.get("q", "").strip(),
            "status": status if status in USER_STATUS_FILTERS else "all",
            "source": source if source in accounts.SOURCES else "",
            "role": role if role in ROLES else "",
            "group": a.get("group", type=int)}


def _filtered_users(f: dict) -> list:
    return users.list_all(get_db(), search=f["q"], status=None if f["status"] == "all" else f["status"],
                          source=f["source"] or None, role=f["role"] or None, group_id=f["group"])


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
    return redirect(url_for({"panel": "admin.users_panel", "cards": "admin.users_cards"}.get(view, "admin.users_list")))


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
                           filters=f, search=f["q"], status=f["status"], counts=users.counts(get_db()),
                           all_groups=group_repo.list_all(get_db()), group_names=_group_names(shown),
                           page_size=PAGE_SIZE)


@bp.route("/users/bulk", methods=["POST"])
@admin_required
def users_bulk():
    """Acción sobre varios usuarios. Se aplica a cada uno con sus protecciones; los errores se listan."""
    action = request.form.get("action", "")
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    if action not in BULK_ACTIONS or not ids:
        flash(_("Select some users and an action."), "error")
        return _back(url_for("admin.users_list"))
    group = None
    if action == "add_group":
        group = group_repo.get_by_id(get_db(), request.form.get("group_id", type=int) or 0)
        if group is None:
            flash(_("Choose the group."), "error")
            return _back(url_for("admin.users_list"))
    done, errors = 0, []
    for uid in ids:
        user = users.get_by_id(get_db(), uid)
        if user is None:
            continue
        try:
            if action in ("disable", "enable"):
                accounts.set_enabled(get_db(), user, g.user, action == "enable")
                _audit("user_enabled" if action == "enable" else "user_disabled", user["username"], user["source"])
            elif action in ("role_user", "role_admin"):
                role = ADMIN if action == "role_admin" else "user"
                accounts.set_role(get_db(), user, g.user, role)
                _audit("user_updated", user["username"], f"role={role}")
            else:
                group_core.add_member(get_db(), group, user)
                _audit("group_member_added", group["name"], user["username"])
        except accounts.AccountError as exc:
            errors.append(f"{user['username']}: {exc.message}")
        else:
            done += 1
    if done:
        flash(ngettext("Done for %(num)s user.", "Done for %(num)s users.", done), "info")
    for error in errors:
        flash(error, "error")
    return _back(url_for("admin.users_list"))


def _user_detail(user) -> dict:
    """Lo común de la ficha (A), los paneles (B) y la edición rápida (C)."""
    cfg = settings()
    labels = {}
    for grp in group_repo.list_all(get_db()):
        labels[grp["name"]] = group_core.label(grp)
        if grp["external_id"]:
            labels[grp["external_id"]] = group_core.label(grp)
    perms = permissions_for(user, cfg)
    return {**_user_groups_context(user),
            "access": explain_access(user, cfg, labels) if user["enabled"] else [],
            "activity": audit.for_user(get_db(), user["username"], 8),
            "role_permissions": [PERMISSION_LABELS[p] for p in PERMISSIONS if p in perms]}


def _pick(rows, wanted: int | None):
    for row in rows:
        if row["id"] == wanted:
            return row
    return rows[0] if rows else None


@bp.route("/users/panel")
@admin_required
def users_panel():
    session["users_view"] = "panel"
    f = _user_filters()
    rows = _filtered_users(f)
    current = _pick(rows, request.args.get("u", type=int))
    tab = request.args.get("tab", "profile")
    tab = tab if tab in USER_TABS else "profile"
    ctx = {}
    if current is not None:
        ctx = {**_user_detail(current), "form": {**dict(current), "enabled": bool(current["enabled"])}}
    return render_template("admin/users/panel.html", users=rows, current=current, tab=tab, filters=f,
                           counts=users.counts(get_db()), **ctx)


@bp.route("/users/cards")
@admin_required
def users_cards():
    session["users_view"] = "cards"
    f = _user_filters()
    rows = _filtered_users(f)
    current = None
    if request.args.get("u", type=int):
        current = _pick(rows, request.args.get("u", type=int))
    sections = [
        ("admins", _("Administrators"), [u for u in rows if u["enabled"] and u["role"] == ADMIN]),
        ("users", _("Users"), [u for u in rows if u["enabled"] and u["role"] != ADMIN]),
        ("disabled", _("Disabled"), [u for u in rows if not u["enabled"]]),
    ]
    return render_template("admin/users/cards.html", sections=sections, current=current, filters=f,
                           group_names=_group_names(rows), **(_user_detail(current) if current else {}))


@bp.route("/users/<int:user_id>/quick", methods=["POST"])
@admin_required
def user_quick(user_id: int):
    """Edición rápida (vista de tarjetas): estado y rol."""
    user = users.get_by_id(get_db(), user_id)
    if user is None:
        abort(404)
    enabled = request.form.get("enabled") == "on"
    role = request.form.get("role", user["role"])
    try:
        if role != user["role"]:
            accounts.set_role(get_db(), user, g.user, role)
            _audit("user_updated", user["username"], f"role={role}")
        if enabled != bool(user["enabled"]):
            accounts.set_enabled(get_db(), users.get_by_id(get_db(), user_id), g.user, enabled)
            _audit("user_enabled" if enabled else "user_disabled", user["username"], user["source"])
    except accounts.AccountError as exc:
        flash(exc.message, "error")
    else:
        flash(_("Changes saved."), "info")
    return _back(url_for("admin.users_cards", u=user_id))


@bp.route("/users/<int:user_id>/status", methods=["POST"])
@admin_required
def user_status(user_id: int):
    """Activa o desactiva una cuenta (también de Entra ID o PAM: desactivar bloquea el acceso)."""
    user = users.get_by_id(get_db(), user_id)
    if user is None:
        abort(404)
    enabled = request.form.get("enabled") == "1"
    try:
        accounts.set_enabled(get_db(), user, g.user, enabled)
    except accounts.AccountError as exc:
        flash(exc.message, "error")
    else:
        _audit("user_enabled" if enabled else "user_disabled", user["username"], user["source"])
        message = _("User «%(name)s» enabled.", name=user["username"]) if enabled else \
            _("User «%(name)s» disabled: they can no longer sign in.", name=user["username"])
        flash(message, "info")
    return _back(url_for("admin.user_edit", user_id=user_id))


def _user_form_data() -> dict:
    f = request.form
    return {
        "display_name": f.get("display_name", "").strip(),
        "email": f.get("email", "").strip(),
        "role": f.get("role", "user"),
        "home_path": f.get("home_path", "").strip(),
        "enabled": f.get("enabled") == "on",
        "password": f.get("password", ""),
    }


@bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_new():
    form = {"source": "local", "role": "user", "enabled": True}
    if request.method == "POST":
        form = {**_user_form_data(), "username": request.form.get("username", "").strip(),
                "source": request.form.get("source", "local"), "groups": _split(request.form.get("groups", ""))}
        try:
            uid = accounts.create_account(get_db(), 
                username=form["username"], source=form["source"], role=form["role"],
                password=form["password"], display_name=form["display_name"], email=form["email"],
                groups=form["groups"], home_path=form["home_path"], enabled=form["enabled"])
        except accounts.AccountError as exc:
            flash(exc.message, "error")
        else:
            _audit("user_created", form["username"], f"{form['source']}:{form['role']}")
            flash(_("User «%(name)s» created.", name=form["username"]), "info")
            return redirect(url_for("admin.user_edit", user_id=uid))
        form.pop("password", None)
    return render_template("admin/user_form.html", user=None, form=form, sources=accounts.SOURCES)


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    user = users.get_by_id(get_db(), user_id)
    if user is None:
        abort(404)
    form = {**dict(user), "enabled": bool(user["enabled"])}
    if request.method == "POST":
        data = _user_form_data()
        try:
            accounts.update_account(get_db(), user, g.user, **data)
        except accounts.AccountError as exc:
            flash(exc.message, "error")
            form.update({k: v for k, v in data.items() if k != "password"})
        else:
            detail = f"role={data['role']} enabled={data['enabled']}" + (" password" if data["password"] else "")
            _audit("user_updated", user["username"], detail)
            flash(_("Changes saved."), "info")
            return _back(url_for("admin.user_edit", user_id=user_id))
        if request.form.get("next"):
            return _back(url_for("admin.user_edit", user_id=user_id))
    return render_template("admin/user_form.html", user=user, form=form, sources=accounts.SOURCES,
                           **_user_detail(user))


def _user_groups_context(user) -> dict:
    """Grupos del usuario (con origen), grupos a los que se puede añadir y grupos del proveedor sin alta."""
    rows = group_core.memberships(get_db(), user)
    mine = {g["id"] for g in rows}
    names = {g["name"] for g in rows} | {g["external_id"] for g in rows if g["external_id"]}
    known = {g["name"] for g in group_repo.list_all(get_db())} | \
        {g["external_id"] for g in group_repo.list_all(get_db()) if g["external_id"]}
    unknown = sorted(group_core.split(user["external_groups"]) - names - known)
    return {"memberships": rows, "unknown_groups": unknown,
            "addable_groups": [g for g in group_repo.list_all(get_db()) if g["id"] not in mine]}


@bp.route("/users/<int:user_id>/groups", methods=["POST"])
@admin_required
def user_group_add(user_id: int):
    user = users.get_by_id(get_db(), user_id)
    group = group_repo.get_by_id(get_db(), request.form.get("group_id", type=int) or 0)
    if user is None or group is None:
        abort(404)
    group_core.add_member(get_db(), group, user)
    _audit("group_member_added", group["name"], user["username"])
    flash(_("«%(user)s» added to the group «%(group)s».", user=user["username"],
            group=group_core.label(group)), "info")
    return _back(url_for("admin.user_edit", user_id=user_id))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id: int):
    user = users.get_by_id(get_db(), user_id)
    if user is None:
        abort(404)
    try:
        accounts.delete_account(get_db(), user, g.user)
    except accounts.AccountError as exc:
        flash(exc.message, "error")
        return redirect(url_for("admin.user_edit", user_id=user_id))
    _audit("user_deleted", user["username"])
    flash(_("User «%(name)s» deleted (their files have not been removed).", name=user["username"]), "info")
    return redirect(url_for("admin.users_list"))


# --------------------------------------------------------------------------- ajustes

def _int(name: str, label: str) -> int:
    try:
        return int(request.form.get(name, ""))
    except ValueError as exc:
        raise ConfigError(_("%(field)s must be a number", field=label)) from exc


def _role_mappings(text: str) -> dict:
    mappings = {}
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, role = line.rpartition("=")
        if not sep or not key.strip():
            raise ConfigError(_("Role mapping, line %(line)s: use the format «group = role»", line=n))
        mappings[key.strip()] = role.strip()
    return mappings


def _runtime_from_form() -> dict:
    f = request.form
    on = lambda name: f.get(name) == "on"  # noqa: E731

    shares = []
    names = f.getlist("share_name")
    ro_groups = f.getlist("share_read_only_groups")
    ro_groups += [""] * (len(names) - len(ro_groups))  # filas nuevas o formularios antiguos
    rows = zip(names, f.getlist("share_label"), f.getlist("share_path"), f.getlist("share_read_only"),
               f.getlist("share_users"), f.getlist("share_groups"), ro_groups)
    for name, label, path, read_only, users_, groups, ro in rows:
        if not name.strip() and not path.strip():
            continue  # fila vacía
        groups = _split(groups)
        shares.append({"name": name.strip(), "label": label.strip(), "path": path.strip(),
                       "read_only": read_only == "1", "users": _split(users_), "groups": groups,
                       # la matriz de accesos los edita; aquí solo se conservan los que siguen en groups
                       "read_only_groups": [g for g in _split(ro) if g.lower() in {x.lower() for x in groups}]})

    return {
        "app_name": f.get("app_name", "").strip(),
        "default_locale": f.get("default_locale", ""),
        "storage": {
            "home_template": f.get("home_template", "").strip(),
            "create_home": on("create_home"),
            "create_shares": on("create_shares"),
            "show_hidden": on("show_hidden"),
            "max_file_size_mb": _int("max_file_size_mb", _("Maximum size per file")),
            "shares": shares,
        },
        "permissions": {"user": {p: on(f"perm_{p}") for p in PERMISSIONS}},
        "auth": {
            "local": {"enabled": on("local_enabled")},
            "pam": {
                "enabled": on("pam_enabled"),
                "service": f.get("pam_service", "login").strip() or "login",
                "allowed_groups": _split(f.get("pam_allowed_groups", "")),
                "admin_groups": _split(f.get("pam_admin_groups", "")),
                "use_system_home": on("pam_use_system_home"),
            },
            "entra": {
                "enabled": on("entra_enabled"),
                "provider": f.get("entra_provider", "oauth2"),
                "tenant_id": f.get("entra_tenant_id", "").strip(),
                "client_id": f.get("entra_client_id", "").strip(),
                "client_secret": f.get("entra_client_secret", "").strip(),
                "redirect_uri": f.get("entra_redirect_uri", "").strip(),
                "scopes": f.get("entra_scopes", "").split(),
                "button_label": f.get("entra_button_label", "").strip(),
                "username_claim": f.get("entra_username_claim", "").strip() or "preferred_username",
                "strip_domain": on("entra_strip_domain"),
                "allowed_groups": _split(f.get("entra_allowed_groups", "")),
                "auto_provision": on("entra_auto_provision"),
                "default_role": f.get("entra_default_role", "user"),
                "role_mappings": _role_mappings(f.get("entra_role_mappings", "")),
                "sync_role_on_login": on("entra_sync_role_on_login"),
                "single_logout": on("entra_single_logout"),
                "authorize_url": f.get("entra_authorize_url", "").strip(),
                "token_url": f.get("entra_token_url", "").strip(),
                "issuer": f.get("entra_issuer", "").strip(),
                "logout_url": f.get("entra_logout_url", "").strip(),
                "timeout_seconds": _int("entra_timeout_seconds", _("Timeout")),
            },
        },
        "security": {
            "max_login_failures": _int("max_login_failures", _("Failed attempts")),
            "lockout_minutes": _int("lockout_minutes", _("Lockout minutes")),
        },
    }


def _render_settings(cfg: dict, status: int = 200):
    info = runtime().info(get_db())
    has_overrides = bool(runtime().overrides(get_db()))
    boot = boot_config()
    return render_template(
        "admin/settings.html", cfg=cfg, info=info, has_overrides=has_overrides,
        providers=list(SSO_PROVIDERS), permissions=PERMISSIONS,
        locales=[(code, locale_display_name(code)) for code in LOCALES],
        secret_set=bool(settings()["auth"]["entra"].get("client_secret")),
        boot={"config_path": boot["_config_path"], "database": boot["database"],
              "host": boot["server"]["host"], "port": boot["server"]["port"],
              "max_upload_mb": boot["server"]["max_upload_mb"],
              "behind_proxy": boot["server"]["behind_proxy"],
              "cookie_secure": boot["session"]["cookie_secure"]},
        effective_json=json.dumps(mask_secrets(runtime_view(settings())), indent=2,
                                  ensure_ascii=False),
    ), status


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    if request.method == "POST":
        draft = None
        try:
            draft = _runtime_from_form()
            runtime().save(get_db(), draft, g.user["username"])
            invalidate_settings()
        except ConfigError as exc:
            flash(_("The changes were not saved: %(error)s", error=exc), "error")
            # Se vuelve a mostrar lo que el admin escribió para que pueda corregirlo
            return _render_settings(_draft_view(draft) if draft else settings(), 400)
        _audit("settings_updated")
        flash(_("Settings saved and applied."), "info")
        return redirect(url_for("admin.settings_page"))
    return _render_settings(settings())


def _draft_view(draft: dict) -> dict:
    return {k: deep_merge(DEFAULTS[k], v) if isinstance(DEFAULTS[k], dict) else v for k, v in draft.items()}


@bp.route("/settings/reset", methods=["POST"])
@admin_required
def settings_reset():
    runtime().reset(get_db(), g.user["username"])
    invalidate_settings()
    _audit("settings_reset")
    flash(_("Web settings discarded; config.json applies again."), "info")
    return redirect(url_for("admin.settings_page"))


# --------------------------------------------------------------------------- auditoría

@bp.route("/audit")
@admin_required
def audit_log():
    username = request.args.get("user", "").strip() or None
    action = request.args.get("action", "").strip() or None
    rows = audit.recent(get_db(), limit=500, username=username, action=action)
    return render_template("admin/audit.html", rows=rows, user_filter=username or "",
                           action_filter=action or "")

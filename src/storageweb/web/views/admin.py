"""Administración web (solo rol admin): usuarios, ajustes y auditoría."""
from __future__ import annotations

import json
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ...core import accounts
from ...core.permissions import PERMISSION_LABELS, ROLE_LABELS
from ...db.repositories import audit, users
from ...i18n import LOCALES, _, locale_display_name
from ...providers import SSO_PROVIDERS
from ...settings import DEFAULTS, PERMISSIONS, ROLES, ConfigError, deep_merge, mask_secrets, runtime_view
from ..context import boot_config, get_db, invalidate_settings, runtime, settings
from ..guards import admin_required, client_ip

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

@bp.route("/users")
@admin_required
def users_list():
    search = request.args.get("q", "").strip()
    return render_template("admin/users.html", users=users.list_all(get_db(), search=search), search=search)


def _user_form_data() -> dict:
    f = request.form
    return {
        "display_name": f.get("display_name", "").strip(),
        "email": f.get("email", "").strip(),
        "role": f.get("role", "user"),
        "groups": _split(f.get("groups", "")),
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
                "source": request.form.get("source", "local")}
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
    form = {**dict(user), "groups": sorted(users.groups_of(user)), "enabled": bool(user["enabled"])}
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
            return redirect(url_for("admin.user_edit", user_id=user_id))
    return render_template("admin/user_form.html", user=user, form=form, sources=accounts.SOURCES)


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
    rows = zip(f.getlist("share_name"), f.getlist("share_label"), f.getlist("share_path"),
               f.getlist("share_read_only"), f.getlist("share_users"), f.getlist("share_groups"))
    for name, label, path, read_only, users_, groups in rows:
        if not name.strip() and not path.strip():
            continue  # fila vacía
        shares.append({"name": name.strip(), "label": label.strip(), "path": path.strip(),
                       "read_only": read_only == "1", "users": _split(users_), "groups": _split(groups)})

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

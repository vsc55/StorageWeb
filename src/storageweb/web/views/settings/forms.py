"""Una página por sección de ajustes, con su formulario (se aplica al guardar) y restablecer campos."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from ....core import branding, maintenance
from ....core.permissions import PERMISSION_LABELS, ROLE_LABELS
from ....db.repositories import users
from ....db.repositories import api_tokens as token_repo
from ....db.repositories import ip_rules as ip_repo
from ....db.repositories import sessions as session_repo
from ....i18n import LOCALES, _, _l, locale_display_name
from ....settings import PERMISSIONS, ROLES, ConfigError, fields, get_path, mask_secrets, runtime_view
from ... import nav
from ...context import boot_config, get_db, invalidate_settings, runtime, settings
from ...guards import admin_required, audit_event, client_ip, safe_next
from . import bp
from . import auth_forms
from .common import checked, form_int, network_context, save_partial


SECTIONS = ("general", "storage", "permissions", "auth", "security", "ips", "sessions", "network", "maintenance",
            "backups", "system")
SECTION_LABELS = {name: nav.PAGES[name].label for name in SECTIONS}
SECTION_DESCRIPTIONS = {
    "general": _l("Name of the application, default language, logo and color."),
    "storage": _l("Where personal folders live and upload limits."),
    "permissions": _l("What the «User» role can do. Administrators always have every permission."),
    "auth": _l("How users sign in. Several methods can be enabled at the same time."),
    "security": _l("Protection against password guessing, automatic IP blocking and API tokens."),
    "ips": _l("Addresses blocked by hand or automatically, and addresses that are never blocked."),
    "maintenance": _l("How long the audit log is kept and how often backups are made."),
    "backups": _l("Backups, database size and cleanup tasks."),
    "sessions": _l("Who is signed in now and which API tokens exist. Closing a session signs that browser out on its "
                   "next request."),
    "network": _l("Public address, reverse proxy and HTTPS. The proxy and the certificate are configured outside "
                  "StorageWeb; here you can check that everything matches."),
    "system": _l("Startup settings and where each value comes from: default, web, config.json or environment."),
}
# Antiguas direcciones de secciones que ahora están en otra página
MOVED = {"shares": "folders"}
WIZARD_STEPS = (1, 2, 3, 4)


def _general() -> dict:
    color = request.form.get("primary_color", "").strip() if checked("custom_color") else ""
    return {"app_name": request.form.get("app_name", "").strip(),
            "default_locale": request.form.get("default_locale", ""),
            "branding": {"primary_color": color}}


def _storage() -> dict:
    return {"storage": {
        "home_location": request.form.get("home_location", "").strip(),
        "home_template": request.form.get("home_template", "").strip(),
        "create_home": checked("create_home"), "create_shares": checked("create_shares"), "show_hidden": checked("show_hidden"),
        "max_file_size_mb": form_int("max_file_size_mb", "storage.max_file_size_mb", _("Maximum size per file")),
        "home_quota_mb": form_int("home_quota_mb", "storage.home_quota_mb", _("Quota of personal folders (MB)")),
        "hidden": [line.strip() for line in request.form.get("hidden", "").splitlines() if line.strip()],
    }}


def _permissions() -> dict:
    return {"permissions": {"user": {p: checked(f"perm_{p}") for p in PERMISSIONS}}}


def _network() -> dict:
    return {"network": {"public_url": request.form.get("public_url", "").strip()}}


def _security() -> dict:
    return {"security": {
        "max_login_failures": form_int("max_login_failures", "security.max_login_failures", _("Failed attempts")),
        "lockout_minutes": form_int("lockout_minutes", "security.lockout_minutes", _("Lockout minutes")),
        "ipban_enabled": checked("ipban_enabled"),
        "ipban_threshold": form_int("ipban_threshold", "security.ipban_threshold", _("Offenses")),
        "ipban_window_minutes": form_int("ipban_window_minutes", "security.ipban_window_minutes", _("Window")),
        "ipban_minutes": form_int("ipban_minutes", "security.ipban_minutes", _("Block duration")),
        "api_tokens": checked("api_tokens"),
        "webdav": checked("webdav"),
        "webdav_passwords": checked("webdav_passwords"),
    }}


def _maintenance() -> dict:
    return {"maintenance": {
        "audit_retention_days": form_int("audit_retention_days", "maintenance.audit_retention_days", _("Audit retention")),
        "backup_interval_hours": form_int("backup_interval_hours", "maintenance.backup_interval_hours",
                                      _("Automatic backups")),
        "backup_keep": form_int("backup_keep", "maintenance.backup_keep", _("Backups to keep")),
    }}


PARSERS = {"general": _general, "storage": _storage, "permissions": _permissions,
           "auth": auth_forms.parse, "security": _security, "network": _network, "maintenance": _maintenance}


def _display(draft: dict | None) -> dict:
    """Lo que se muestra tras un error: los ajustes efectivos con lo que escribió el admin encima."""
    if not draft:
        return settings()
    return {**settings(), **draft}


# --------------------------------------------------------------------------- páginas

def _context(section: str, cfg: dict) -> dict:
    origins = runtime().origins(get_db())
    info = runtime().info(get_db())
    return {
        "section": section, "cfg": cfg, "SECTION_LABELS": SECTION_LABELS,
        "description": SECTION_DESCRIPTIONS[section], "origins": origins,
        "is_locked": lambda path: bool(runtime().lock_of(path)),
        "default_text": lambda path: fields.display(path, get_path(runtime().defaults(), path)),
        "form_default": lambda path: fields.form_value(path, get_path(runtime().defaults(), path)),
        "profile": runtime().profile,
        "info": info, "locales": [(code, locale_display_name(code)) for code in LOCALES],
        "permissions": PERMISSIONS, "PERMISSION_LABELS": PERMISSION_LABELS,
        "ROLES": ROLES, "ROLE_LABELS": ROLE_LABELS,
    }


def _origin_rows(origins: dict) -> list[dict]:
    """Campos que no tienen su valor predeterminado (o que están bloqueados), con su origen y su página."""
    order = {"env": 0, "file": 1, "web": 2}
    return [{"path": path, "label": fields.label(path), "origin": origin,
             "value": fields.display(path, get_path(settings(), path)),
             "url": nav.PAGES[nav.page_for_path(path)].url() + "#f-" + path.replace(".", "-")}
            for path, origin in sorted(origins.items(), key=lambda item: (order[item[1]], item[0]))]


def _render(section: str, cfg: dict, status: int = 200, error: ConfigError | None = None):
    ctx = _context(section, cfg)
    if section == "system":
        boot = boot_config()
        ctx.update(boot={"config_path": boot["_config_path"], "database": boot["database"], "host": boot["server"]["host"],
                         "port": boot["server"]["port"], "max_upload_mb": boot["server"]["max_upload_mb"],
                         "behind_proxy": boot["server"]["behind_proxy"],
                         "cookie_secure": boot["session"]["cookie_secure"]},
                   effective_json=json.dumps(mask_secrets(runtime_view(settings())), indent=2, ensure_ascii=False),
                   origin_rows=_origin_rows(ctx["origins"]), info=ctx["info"])
    if section == "network":
        ctx.update(network_context(cfg))
    if section == "ips":
        ctx.update(ip_bans=ip_repo.list_rules(get_db(), "ban"), ip_allows=ip_repo.list_rules(get_db(), "allow"),
                   my_ip=client_ip(), now=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if section == "backups":
        boot = boot_config()
        ctx.update(db=maintenance.db_stats(get_db(), boot["database"]), backups=maintenance.list_backups(boot),
                   backup_folder=str(maintenance.backup_dir(boot)), maint_state=maintenance.state(get_db()))
    if section == "sessions":
        rows = session_repo.list_all(get_db())
        ctx.update(sessions=rows, current_sid=g.get("session_id"), all_tokens=token_repo.list_all(get_db()),
                   session_users=len({r["user_id"] for r in rows}),
                   lifetime_hours=boot_config()["session"]["lifetime_hours"])
    if section == "auth":
        ctx.update(auth_forms.context(cfg), user_counts=users.count_by_source(get_db()))
    return render_template(f"admin/settings/{section}.html", error=error,
                           error_field=error.field if error else None, **ctx), status


@bp.route("", methods=["GET", "POST"])
@admin_required
def index():
    return redirect(url_for("settings.section", name="general"), code=303 if request.method == "POST" else 302)


@bp.route("/<name>", methods=["GET", "POST"])
@admin_required
def section(name: str):
    if name in MOVED and request.method == "GET":
        return redirect(nav.PAGES[MOVED[name]].url(), code=301)
    if name not in SECTIONS:
        abort(404)
    if request.method == "POST":
        if name not in PARSERS:
            abort(405)
        draft, error = save_partial(PARSERS[name])
        if error:
            return _render(name, _display(draft), 400, error)
        audit_event("settings_updated", None, name)
        flash(_("Settings saved and applied."), "info")
        return redirect(url_for("settings.section", name=name))
    return _render(name, settings())


@bp.route("/reset", methods=["POST"])
@admin_required
def reset():
    runtime().reset(get_db(), g.user["username"])
    invalidate_settings()
    audit_event("settings_reset")
    flash(_("Web settings discarded: the default values apply again."), "info")
    return redirect(url_for("settings.section", name="system"))


@bp.route("/reset-field", methods=["POST"])
@admin_required
def reset_field():
    path = request.form.get("path", "")
    target = safe_next(request.form.get("next")) if request.form.get("next") else \
        nav.PAGES[nav.page_for_path(path)].url()
    if runtime().origins(get_db()).get(path) != "web":
        return redirect(target)
    try:
        runtime().reset_path(get_db(), path, g.user["username"])
    except ConfigError as exc:
        flash(_("It cannot be reset: %(error)s", error=exc), "error")
        return redirect(target)
    invalidate_settings()
    audit_event("settings_field_reset", None, path)
    flash(_("«%(path)s» has its default value again.", path=fields.label(path)), "info")
    return redirect(target)

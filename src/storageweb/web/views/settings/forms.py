"""Una página por sección de ajustes, con su formulario (se aplica al guardar) y restablecer campos."""
from __future__ import annotations

import json

from flask import abort, flash, g, redirect, render_template, request, url_for

from .... import siem
from ....core import branding, links, maintenance, offsite, passwords, storage, thumbnails
from ....providers import local
from ....core.backup import BackupError
from ....core.permissions import PERMISSION_LABELS, ROLE_LABELS
from ....db.repositories import users
from ....db.repositories import api_tokens as token_repo
from ....db.repositories import ip_rules as ip_repo
from ....db.repositories import sessions as session_repo
from ....i18n import LOCALES, _, _l, locale_display_name
from ....settings import PERMISSIONS, ROLES, ConfigError, fields, get_path, mask_secrets, runtime_view
from ... import nav
from ...context import boot_config, external_url, get_db, invalidate_settings, runtime, settings
from ...guards import admin_required, audit_event, client_ip
from . import bp
from . import auth_forms
from ....settings import store as settings_store
from ...forms import next_url, split_lines, split_list
from .common import checked, form_int, network_context, save_partial, to_section
from ..links import listing_context as link_listing
from ....clock import now_iso


SECTIONS = ("general", "storage", "quotas", "security_status", "vulnerabilities", "auth", "passwords", "security",
            "clients", "ips",
            "sessions", "network",
            "sharing", "server_folders", "files", "preview", "audit_settings", "auto_backups", "monitoring", "backups", "system")
SECTION_LABELS = {name: nav.PAGES[name].label for name in SECTIONS}
SECTION_DESCRIPTIONS = {
    "general": _l("Name of the application, default language, logo and color."),
    "storage": _l("Where personal folders live and how they are created."),
    "quotas": _l("How much each personal folder can hold, whether what does not fit is blocked and how often the "
                 "usage is measured again."),
    "sharing": _l("Links to share a file or a folder with people without an account, and drop boxes to receive "
                  "files. Who can create them is the permission «Share with links» of the role."),
    "server_folders": _l("Which folders of the server disk can hold shared and personal folders, and the only ones "
                         "that Browse shows on it."),
    "files": _l("What the file browser shows, what does not exist for anyone, the largest file and how folders "
                "with many items are shown."),
    "audit_settings": _l("How long the audit log is kept, from which level events are recorded and sending them to "
                         "a SIEM or syslog."),
    "auto_backups": _l("Backups made by the service itself and the copy outside the server."),
    "monitoring": _l("Metrics for Prometheus: who can read them and how."),
    "auth": _l("How users sign in. Several methods can be enabled at the same time."),
    "security": _l("Protection against password guessing and automatic IP blocking."),
    "passwords": _l("What a new password of a local account must have and which ones are rejected: common ones, "
                    "forbidden words and passwords from known data breaches."),
    "security_status": _l("Security at a glance: key figures, a review of what is right and what to review (with "
                          "where to change it) and the latest security events."),
    "vulnerabilities": _l("Known vulnerabilities and new versions of the installed libraries (Python and JavaScript), "
                          "checked with the button or automatically."),
    "clients": _l("How scripts, apps and network drives reach the files: personal API tokens and WebDAV."),
    "ips": _l("Addresses blocked by hand or automatically, and addresses that are never blocked."),
    "preview": _l("Which files open in the browser without downloading them, how large they can be and whether "
                  "Markdown diagrams are drawn."),
    "backups": _l("Backups, database size and cleanup tasks."),
    "sessions": _l("Who is signed in now and which API tokens exist. Closing a session signs that browser out on its "
                   "next request."),
    "network": _l("Public address, reverse proxy and HTTPS. The proxy and the certificate are configured outside "
                  "StorageWeb; here you can check that everything matches."),
    "system": _l("This installation (version, server, database, folders and components) with a report to download, "
                 "the startup settings and where each value comes from: default, web, config.json or environment."),
}
# Antiguas direcciones de secciones que ahora están en otra página
MOVED = {"shares": "folders", "maintenance": "auto_backups", "permissions": "permissions"}   # Roles: roles.index
WIZARD_STEPS = (1, 2, 3, 4)


def _general() -> dict:
    color = request.form.get("primary_color", "").strip() if checked("custom_color") else ""
    return {"app_name": request.form.get("app_name", "").strip(),
            "default_locale": request.form.get("default_locale", ""),
            "branding": {"primary_color": color, "login_art": request.form.get("login_art", "").strip()}}


def _storage() -> dict:
    return {"storage": {
        "home_location": request.form.get("home_location", "").strip(),
        "home_template": request.form.get("home_template", "").strip(),
        "create_home": checked("create_home"),
    }}


def _quotas() -> dict:
    return {"storage": {
        "home_quota_mb": form_int("home_quota_mb", "storage.home_quota_mb", _("Quota of personal folders (MB)")),
        "quota_enforce": checked("quota_enforce"),
        "quota_refresh_minutes": form_int("quota_refresh_minutes", "storage.quota_refresh_minutes",
                                          _("Measure the quota usage again every (minutes)")),
        "quota_warn_percent": form_int("quota_warn_percent", "storage.quota_warn_percent",
                                       _("Warn from (percent of the quota)")),
    }}


def _sharing() -> dict:
    return {"sharing": {
        "links": checked("sharing_links"),
        "default_days": form_int("sharing_default_days", "sharing.default_days", _("Days a link lasts by default")),
        "max_days": form_int("sharing_max_days", "sharing.max_days", _("Days a link can last at most")),
        "require_password": checked("sharing_require_password"),
        "upload_links": checked("sharing_upload_links"),
        "keep_days": form_int("sharing_keep_days", "sharing.keep_days", _("Keep removed or expired links (days)")),
        "history_days": form_int("sharing_history_days", "sharing.history_days",
                                 _("Keep the history of the links (days)")),
    }}


def _passwords() -> dict:
    return {"security": {
        "password_min_length": form_int("password_min_length", "security.password_min_length",
                                        _("Minimum password length")),
        "password_min_distinct": form_int("password_min_distinct", "security.password_min_distinct",
                                          _("Different characters at least")),
        "password_require": request.form.getlist("password_require"),
        "password_reject_username": checked("password_reject_username"),
        "password_check": checked("password_check"),
        "password_list_urls": split_lines("password_list_urls"),
        "password_blocklist": split_lines("password_blocklist"),
        "password_breach_check": checked("password_breach_check"),
    }}


def _server_folders() -> dict:
    # Una por línea (una ruta puede tener espacios); el loader las valida y las deja absolutas
    return {"storage": {"allowed_folders": split_lines("allowed_folders")}}


def _files() -> dict:
    return {"storage": {
        "show_hidden": checked("show_hidden"), "create_shares": checked("create_shares"),
        "max_file_size_mb": form_int("max_file_size_mb", "storage.max_file_size_mb", _("Maximum size per file")),
        "page_size": form_int("page_size", "storage.page_size", _("Items shown at once")),
        "listing_mode": request.form.get("listing_mode", "").strip(),
        "hidden": split_lines("hidden"),
        "upload_stale_hours": form_int("upload_stale_hours", "storage.upload_stale_hours",
                                       _("Discard unfinished uploads after (hours)")),
        "search_max_results": form_int("search_max_results", "storage.search_max_results",
                                       _("Search: at most (results)")),
        "search_seconds": form_int("search_seconds", "storage.search_seconds", _("Search: at most (seconds)")),
        "search_max_folders": form_int("search_max_folders", "storage.search_max_folders",
                                       _("Search: at most (folders looked at)")),
    }}



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
    }}


def _vulnerabilities() -> dict:
    return {"security": {"dependency_check_hours": form_int("dependency_check_hours", "security.dependency_check_hours",
                                                            _("Check the libraries automatically every (hours)"))}}


def _clients() -> dict:
    return {"security": {
        "api_tokens": checked("api_tokens"),
        "api_token_max_days": form_int("api_token_max_days", "security.api_token_max_days",
                                       _("Longest API token lifetime (days)")),
        "api_token_unused_days": form_int("api_token_unused_days", "security.api_token_unused_days",
                                          _("Warn about tokens unused for (days)")),
        "webdav": checked("webdav"),
        "webdav_passwords": checked("webdav_passwords"),
    }}


def _preview() -> dict:
    return {"preview": {
        "enabled": checked("preview_enabled"),
        "diagrams": checked("preview_diagrams"),
        "highlight": checked("preview_highlight"),
        **{key: checked(f"preview_{key}") for key in ("images", "pdf", "video", "audio", "thumbnails")},
        "thumbnail_max_mb": form_int("preview_thumbnail_max_mb", "preview.thumbnail_max_mb",
                                     _("Thumbnails: largest image (MB)")),
        "thumbnail_cache_mb": form_int("preview_thumbnail_cache_mb", "preview.thumbnail_cache_mb",
                                       _("Thumbnails: space for the cache (MB)")),
        "max_mb": form_int("preview_max_mb", "preview.max_mb", _("Largest file to view (MB)")),
        "extensions": _extensions("preview_extensions"),
        "blocked_extensions": _extensions("preview_blocked_extensions"),
    }}


def _extensions(name: str) -> list[str]:
    """Una lista de extensiones escrita a mano: separadas por comas, espacios o líneas."""
    return [ext for item in split_list(request.form.get(name, "")) for ext in item.split()]


def _auto_backups() -> dict:
    return {"maintenance": {
        "backup_interval_hours": form_int("backup_interval_hours", "maintenance.backup_interval_hours",
                                      _("Automatic backups")),
        "backup_keep": form_int("backup_keep", "maintenance.backup_keep", _("Backups to keep")),
        "offsite_location": request.form.get("offsite_location", "").strip(),
        "offsite_path": request.form.get("offsite_path", "").strip(),
        "offsite_keep": form_int("offsite_keep", "maintenance.offsite_keep", _("Backups to keep in the location")),
    }}


def _audit_settings() -> dict:
    return {"maintenance": {
        "audit_retention_days": form_int("audit_retention_days", "maintenance.audit_retention_days", _("Audit retention")),
    }, "audit": {
        "min_level": request.form.get("audit_min_level", "debug"),
        "forward_min_level": request.form.get("audit_forward_min_level", "info"),
        "syslog": request.form.get("audit_syslog", "").strip(),
        "syslog_format": request.form.get("audit_syslog_format", "rfc5424"),
        "syslog_facility": request.form.get("audit_syslog_facility", "local0"),
        "syslog_ca": request.form.get("audit_syslog_ca", "").strip(),
        "tls_verify": checked("audit_tls_verify"),
        "file": request.form.get("audit_file", "").strip(),
    }}


def _monitoring() -> dict:
    return {"metrics": {
        "enabled": checked("metrics_enabled"),
        "token": request.form.get("metrics_token", "").strip(),  # vacío = conservar el que hay
        "allowed_networks": split_list(request.form.get("metrics_allowed_networks", "")),
    }}


PARSERS = {"general": _general, "storage": _storage, "quotas": _quotas, "server_folders": _server_folders, "passwords": _passwords, "sharing": _sharing, "files": _files,
           "auth": auth_forms.parse, "security": _security, "clients": _clients, "network": _network, "preview": _preview,
           "audit_settings": _audit_settings, "auto_backups": _auto_backups, "monitoring": _monitoring,
           "vulnerabilities": _vulnerabilities}


def _share_rows(rows) -> list[dict]:
    """Los enlaces para la tabla de la administración: con su estado, sin el token (ni cifrado: un administrador no
    abre los enlaces de los demás desde aquí; los puede quitar)."""
    return [{**{k: row[k] for k in row.keys() if k not in ("token_hash", "token_enc", "password_hash")},
             "has_password": bool(row["password_hash"]), "state": links.state(row)} for row in rows]


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
        "login_arts": list(branding.LOGIN_ART_LABELS.items()),
        "permissions": PERMISSIONS, "PERMISSION_LABELS": PERMISSION_LABELS,
        "ROLES": ROLES, "ROLE_LABELS": ROLE_LABELS,
        "metrics_token_set": bool(settings()["metrics"]["token"]),
        "metrics_url": external_url("metrics.metrics_page"),
    }


def _origin_rows(origins: dict) -> list[dict]:
    """Campos que no tienen su valor predeterminado (o que están bloqueados), con su origen, su página y, los
    guardados desde la web, quién y cuándo los cambió."""
    order = {"env": 0, "file": 1, "web": 2}
    changes = runtime().changes(get_db())
    return [{"path": path, "label": fields.label(path), "origin": origin,
             "value": fields.display(path, get_path(settings(), path)),
             "changed": changes.get(path) if origin == "web" else None,
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
                   origin_rows=_origin_rows(ctx["origins"]), info=ctx["info"],
                   profiles=settings_store.profiles(get_db()))
        from . import system as system_info  # noqa: PLC0415 (system importa este paquete)
        ctx.update(system_info.context())
    if section == "network":
        ctx.update(network_context(cfg))
    if section == "sharing":
        rows, extra = link_listing(_share_rows(links.all_links(get_db())), "admin_links_show")
        ctx.update(share_links=rows, **extra)
    if section == "preview":
        ctx.update(thumbnails_available=thumbnails.available(), pillow_version=thumbnails.pillow_version(),
                   thumbnail_usage=thumbnails.usage(boot_config()["data_dir"]))
    if section == "passwords":
        ctx.update(password_kinds=list(local.KIND_LABELS.items()),
                   password_list=passwords.status(boot_config()["data_dir"]))
    if section == "server_folders":
        # Lo que hay ahora en el disco y si cabe en la lista que se muestra (tras un error, la que se escribió)
        ctx.update(disk_folders=storage.disk_folders(get_db(), settings(), cfg["storage"]["allowed_folders"]))
    if section == "security_status":
        from .security_status import security_context  # noqa: PLC0415 (importa este paquete)
        ctx.update(security_context(cfg))
    if section == "vulnerabilities":
        from .security_status import vulnerabilities_context  # noqa: PLC0415
        ctx.update(vulnerabilities_context())
    if section == "ips":
        ctx.update(ip_bans=ip_repo.list_rules(get_db(), "ban"), ip_allows=ip_repo.list_rules(get_db(), "allow"),
                   my_ip=client_ip(), now=now_iso())
    if section == "audit_settings":
        ctx.update(forward_status=siem.FORWARDER.status())
    if section == "backups":
        boot = boot_config()
        ctx.update(db=maintenance.db_stats(get_db(), boot["database"]), backups=maintenance.list_backups(boot),
                   backup_folder=str(maintenance.backup_dir(boot)), maint_state=maintenance.state(get_db()),
                   offsite_where=offsite.where(settings()) if offsite.enabled(settings()) else "")
        if offsite.enabled(settings()) and request.args.get("remote") == "1":
            # Solo si se pide: listar la ubicación es una conexión (no cada vez que se abre la página)
            try:
                ctx.update(remote_backups=offsite.list_remote(settings()), remote_error="")
            except BackupError as exc:
                ctx.update(remote_backups=[], remote_error=str(exc))
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
    return to_section("system")


@bp.route("/reset-field", methods=["POST"])
@admin_required
def reset_field():
    path = request.form.get("path", "")
    target = next_url(nav.PAGES[nav.page_for_path(path)].url())
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

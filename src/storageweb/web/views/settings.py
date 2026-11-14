"""Ajustes desde la web (solo rol admin), una página por sección.

Cada sección guarda solo sus campos: se combinan sobre los ajustes efectivos y
``RuntimeSettings.save`` guarda la diferencia con config.json. Así cada campo sabe si su valor
viene de config.json o de la web (``changed_paths``) y se puede restablecer uno a uno.

El asistente de Entra ID (``/admin/settings/entra/setup``) guarda paso a paso los mismos campos
que la sección «Inicio de sesión» y termina con la comprobación de la conexión.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_file, session,
                   url_for)

from ...core import branding, ipban, maintenance
from ...core.permissions import PERMISSION_LABELS, ROLE_LABELS
from ...db.repositories import audit, users
from ...db.repositories import api_tokens as token_repo
from ...db.repositories import ip_rules as ip_repo
from ...db.repositories import sessions as session_repo
from ...i18n import LOCALES, _, _l, format_size, locale_display_name, ngettext
from ...providers import SSO_PROVIDERS, entra_check, entra_register
from ...settings import PERMISSIONS, ROLES, ConfigError, mask_secrets, merge_overrides, runtime_view
from .. import nav
from ..context import boot_config, external_url, get_db, invalidate_settings, runtime, settings
from ..guards import admin_required, client_ip, safe_next

bp = Blueprint("settings", __name__, url_prefix="/admin/settings")

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
    "system": _l("Startup settings (config.json only) and values changed from the web."),
}
# Antiguas direcciones de secciones que ahora están en otra página
MOVED = {"shares": "folders"}
WIZARD_STEPS = (1, 2, 3, 4)


def _audit(action: str, target: str | None = None, detail: str | None = None) -> None:
    audit.log(get_db(), action, target, username=g.user["username"], ip=client_ip(), detail=detail)


# --------------------------------------------------------------------------- lectura de formularios

def _split(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n]", value or "") if x.strip()]


def _on(name: str) -> bool:
    return request.form.get(name) == "on"


def _int(name: str, field: str, label: str) -> int:
    try:
        return int(request.form.get(name, ""))
    except ValueError as exc:
        raise ConfigError(_("%(field)s must be a number", field=label), field) from exc


def _role_mappings() -> dict:
    f = request.form
    if "entra_role_mappings" in f:  # formato de texto «grupo = rol», una línea por mapeo
        mappings = {}
        for n, line in enumerate(f.get("entra_role_mappings", "").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, role = line.rpartition("=")
            if not sep or not key.strip():
                raise ConfigError(_("Role mapping, line %(line)s: use the format «group = role»", line=n),
                                  "auth.entra.role_mappings")
            mappings[key.strip()] = role.strip()
        return mappings
    return {grp.strip(): role for grp, role in zip(f.getlist("mapping_group"), f.getlist("mapping_role"))
            if grp.strip()}


def _general() -> dict:
    color = request.form.get("primary_color", "").strip() if _on("custom_color") else ""
    return {"app_name": request.form.get("app_name", "").strip(),
            "default_locale": request.form.get("default_locale", ""),
            "branding": {"primary_color": color}}


def _storage() -> dict:
    return {"storage": {
        "home_template": request.form.get("home_template", "").strip(),
        "create_home": _on("create_home"), "create_shares": _on("create_shares"), "show_hidden": _on("show_hidden"),
        "max_file_size_mb": _int("max_file_size_mb", "storage.max_file_size_mb", _("Maximum size per file")),
    }}


def _permissions() -> dict:
    return {"permissions": {"user": {p: _on(f"perm_{p}") for p in PERMISSIONS}}}


def _entra_connection() -> dict:
    f = request.form
    data = {"tenant_id": f.get("entra_tenant_id", "").strip(), "client_id": f.get("entra_client_id", "").strip(),
            "redirect_uri": f.get("entra_redirect_uri", "").strip()}
    if f.get("entra_client_secret", "").strip():  # vacío = conservar el actual
        data["client_secret"] = f["entra_client_secret"].strip()
    return data


def _auth() -> dict:
    f = request.form
    entra = {
        **_entra_connection(),
        "enabled": _on("entra_enabled"),
        "provider": f.get("entra_provider", "oauth2"),
        "scopes": f.get("entra_scopes", "").split(),
        "button_label": f.get("entra_button_label", "").strip(),
        "username_claim": f.get("entra_username_claim", "").strip() or "preferred_username",
        "strip_domain": _on("entra_strip_domain"),
        "allowed_groups": _split(f.get("entra_allowed_groups", "")),
        "auto_provision": _on("entra_auto_provision"),
        "default_role": f.get("entra_default_role", "user"),
        "role_mappings": _role_mappings(),
        "sync_role_on_login": _on("entra_sync_role_on_login"),
        "single_logout": _on("entra_single_logout"),
        "authorize_url": f.get("entra_authorize_url", "").strip(),
        "token_url": f.get("entra_token_url", "").strip(),
        "issuer": f.get("entra_issuer", "").strip(),
        "logout_url": f.get("entra_logout_url", "").strip(),
        "timeout_seconds": _int("entra_timeout_seconds", "auth.entra.timeout_seconds", _("Timeout")),
        "secret_expires": _secret_expires(f.get("entra_secret_expires", "").strip()),
    }
    return {"auth": {
        "local": {"enabled": _on("local_enabled")},
        "pam": {"enabled": _on("pam_enabled"), "service": f.get("pam_service", "login").strip() or "login",
                "allowed_groups": _split(f.get("pam_allowed_groups", "")),
                "admin_groups": _split(f.get("pam_admin_groups", "")),
                "use_system_home": _on("pam_use_system_home")},
        "entra": entra,
    }}


def _secret_expires(date_text: str) -> str:
    """La fecha del formulario (AAAA-MM-DD). Si es el mismo día que la guardada, se conserva la hora exacta."""
    current = settings()["auth"]["entra"].get("secret_expires", "")
    if current and current[:10] == date_text:
        return current
    return date_text


def _network() -> dict:
    return {"network": {"public_url": request.form.get("public_url", "").strip()}}


def _security() -> dict:
    return {"security": {
        "max_login_failures": _int("max_login_failures", "security.max_login_failures", _("Failed attempts")),
        "lockout_minutes": _int("lockout_minutes", "security.lockout_minutes", _("Lockout minutes")),
        "ipban_enabled": _on("ipban_enabled"),
        "ipban_threshold": _int("ipban_threshold", "security.ipban_threshold", _("Offenses")),
        "ipban_window_minutes": _int("ipban_window_minutes", "security.ipban_window_minutes", _("Window")),
        "ipban_minutes": _int("ipban_minutes", "security.ipban_minutes", _("Block duration")),
        "api_tokens": _on("api_tokens"),
    }}


def _maintenance() -> dict:
    return {"maintenance": {
        "audit_retention_days": _int("audit_retention_days", "maintenance.audit_retention_days", _("Audit retention")),
        "backup_interval_hours": _int("backup_interval_hours", "maintenance.backup_interval_hours",
                                      _("Automatic backups")),
        "backup_keep": _int("backup_keep", "maintenance.backup_keep", _("Backups to keep")),
    }}


PARSERS = {"general": _general, "storage": _storage, "permissions": _permissions,
           "auth": _auth, "security": _security, "network": _network, "maintenance": _maintenance}


# --------------------------------------------------------------------------- guardar

def save_partial(partial_builder) -> tuple[dict | None, ConfigError | None]:
    """Combina lo del formulario con los ajustes efectivos, valida y guarda. Devuelve (vista, error)."""
    draft = None
    try:
        draft = merge_overrides(runtime_view(settings()), partial_builder())
        runtime().save(get_db(), draft, g.user["username"])
    except ConfigError as exc:
        return draft, exc
    invalidate_settings()
    return draft, None


def _display(draft: dict | None) -> dict:
    """Lo que se muestra tras un error: los ajustes efectivos con lo que escribió el admin encima."""
    if not draft:
        return settings()
    return {**settings(), **draft}


# --------------------------------------------------------------------------- páginas

def _context(section: str, cfg: dict) -> dict:
    changed = runtime().changed_paths(get_db())
    check = session.get("entra_check")
    info = runtime().info(get_db())
    return {
        "section": section, "cfg": cfg, "SECTION_LABELS": SECTION_LABELS,
        "description": SECTION_DESCRIPTIONS[section], "changed": changed,
        "info": info, "locales": [(code, locale_display_name(code)) for code in LOCALES],
        "providers": list(SSO_PROVIDERS), "permissions": PERMISSIONS, "PERMISSION_LABELS": PERMISSION_LABELS,
        "ROLES": ROLES, "ROLE_LABELS": ROLE_LABELS,
        "secret_set": bool(settings()["auth"]["entra"].get("client_secret")),
        "user_counts": users.count_by_source(get_db()),
        "entra_check": check, "entra_check_ok": entra_check.summary(check["results"]) if check else None,
        "redirect_default": _redirect_uri(cfg["auth"]["entra"]),
    }


def _secret_days(expires: str) -> int | None:
    if not expires:
        return None
    return (datetime.fromisoformat(expires) - datetime.now(timezone.utc)).days


def _render(section: str, cfg: dict, status: int = 200, error: ConfigError | None = None):
    ctx = _context(section, cfg)
    if section == "system":
        boot = boot_config()
        ctx.update(boot={"config_path": boot["_config_path"], "database": boot["database"], "host": boot["server"]["host"],
                         "port": boot["server"]["port"], "max_upload_mb": boot["server"]["max_upload_mb"],
                         "behind_proxy": boot["server"]["behind_proxy"],
                         "cookie_secure": boot["session"]["cookie_secure"]},
                   effective_json=json.dumps(mask_secrets(runtime_view(settings())), indent=2, ensure_ascii=False),
                   changed_list=sorted(ctx["changed"]))
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
        ctx["secret_days"] = _secret_days(cfg["auth"]["entra"].get("secret_expires", ""))
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
        _audit("settings_updated", None, name)
        flash(_("Settings saved and applied."), "info")
        return redirect(url_for("settings.section", name=name))
    return _render(name, settings())


@bp.route("/reset", methods=["POST"])
@admin_required
def reset():
    runtime().reset(get_db(), g.user["username"])
    invalidate_settings()
    _audit("settings_reset")
    flash(_("Web settings discarded; config.json applies again."), "info")
    return redirect(url_for("settings.section", name="system"))


@bp.route("/reset-field", methods=["POST"])
@admin_required
def reset_field():
    path = request.form.get("path", "")
    target = safe_next(request.form.get("next")) if request.form.get("next") else \
        nav.PAGES[nav.page_for_path(path)].url()
    if path not in runtime().changed_paths(get_db()):
        return redirect(target)
    try:
        runtime().reset_path(get_db(), path, g.user["username"])
    except ConfigError as exc:
        flash(_("It cannot be reset: %(error)s", error=exc), "error")
        return redirect(target)
    invalidate_settings()
    _audit("settings_field_reset", None, path)
    flash(_("«%(path)s» uses the value of config.json again.", path=path), "info")
    return redirect(target)


# --------------------------------------------------------------------------- marca

@bp.route("/branding/logo", methods=["POST"])
@admin_required
def branding_logo():
    item = request.files.get("logo")
    cfg = boot_config()
    try:
        if not item or not item.filename:
            raise branding.BrandingError(_("Choose an image."))
        name = branding.save_logo(cfg, item.filename, item.read(branding.MAX_BYTES + 1))
    except branding.BrandingError as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.section", name="general"))
    _draft, error = save_partial(lambda: {"branding": {"logo": name}})
    if error:
        flash(str(error), "error")
    else:
        _audit("branding_logo_updated", None, name)
        flash(_("Logo updated."), "info")
    return redirect(url_for("settings.section", name="general"))


@bp.route("/branding/logo/delete", methods=["POST"])
@admin_required
def branding_logo_delete():
    branding.remove_logo(boot_config())
    save_partial(lambda: {"branding": {"logo": ""}})
    _audit("branding_logo_removed")
    flash(_("Logo removed."), "info")
    return redirect(url_for("settings.section", name="general"))


# --------------------------------------------------------------------------- IPs bloqueadas y permitidas

@bp.route("/security/ip", methods=["POST"])
@admin_required
def ip_add():
    kind = request.form.get("kind")
    network, reason = request.form.get("network", ""), request.form.get("reason", "")
    try:
        if kind == "ban":
            net = ipban.ban(get_db(), network, by=g.user["username"], reason=reason,
                            minutes=request.form.get("minutes", 0, type=int) or 0, current_ip=client_ip())
            _audit("ip_banned", net, f"manual:{reason}"[:200])
            flash(_("%(network)s blocked.", network=net), "info")
        elif kind == "allow":
            net = ipban.allow(get_db(), network, by=g.user["username"], reason=reason)
            _audit("ip_allowed", net, reason[:200] or None)
            flash(_("%(network)s added to the allow list.", network=net), "info")
        else:
            abort(400)
    except ipban.IPBanError as exc:
        flash(str(exc), "error")
    return redirect(url_for("settings.section", name="ips"))


@bp.route("/security/ip/<int:rule_id>/delete", methods=["POST"])
@admin_required
def ip_remove(rule_id: int):
    rule = ipban.remove(get_db(), rule_id)
    if rule:
        _audit("ip_unbanned" if rule["kind"] == "ban" else "ip_allow_removed", rule["network"])
        flash(_("%(network)s removed.", network=rule["network"]), "info")
    return redirect(url_for("settings.section", name="ips"))


# --------------------------------------------------------------------------- sesiones

@bp.route("/sessions/close-all", methods=["POST"])
@admin_required
def sessions_close_all():
    """Cierra todas las sesiones salvo la del admin que lo pide."""
    closed = 0
    for row in session_repo.list_all(get_db()):
        if row["id"] != g.get("session_id"):
            session_repo.delete(get_db(), row["id"])
            closed += 1
    _audit("sessions_closed", "*", str(closed))
    flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    return redirect(url_for("settings.section", name="sessions"))


IDLE_CHOICES = (1, 24, 24 * 7, 24 * 30)  # horas


@bp.route("/sessions/close-selected", methods=["POST"])
@admin_required
def sessions_close_selected():
    """Cierra las sesiones marcadas en la lista (nunca la del admin que lo pide)."""
    closed = 0
    for sid in set(request.form.getlist("sids")):
        if sid != g.get("session_id") and session_repo.get(get_db(), sid) is not None:
            session_repo.delete(get_db(), sid)
            closed += 1
    if closed:
        _audit("sessions_closed", "selected", str(closed))
        flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    else:
        flash(_("Select at least one session."), "error")
    return redirect(url_for("settings.section", name="sessions"))


@bp.route("/sessions/close-idle", methods=["POST"])
@admin_required
def sessions_close_idle():
    """Cierra las sesiones sin actividad desde hace más de las horas elegidas."""
    hours = request.form.get("hours", type=int)
    if hours not in IDLE_CHOICES:
        abort(400)
    before = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    closed = 0
    for row in session_repo.list_all(get_db()):
        if row["id"] != g.get("session_id") and row["last_seen"] < before:
            session_repo.delete(get_db(), row["id"])
            closed += 1
    _audit("sessions_closed", f"idle>{hours}h", str(closed))
    flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    return redirect(url_for("settings.section", name="sessions"))


# --------------------------------------------------------------------------- mantenimiento

@bp.route("/maintenance/vacuum", methods=["POST"])
@admin_required
def maintenance_vacuum():
    before, after = maintenance.vacuum(get_db(), boot_config()["database"])
    _audit("db_vacuum", None, f"{before}->{after}")
    flash(_("Database compacted: %(before)s → %(after)s.", before=format_size(before), after=format_size(after)), "info")
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/purge", methods=["POST"])
@admin_required
def maintenance_purge():
    days = settings()["maintenance"]["audit_retention_days"]
    if not days:
        flash(_("Set the audit retention first."), "error")
    else:
        removed = maintenance.purge_audit(get_db(), days)
        _audit("audit_purged", None, str(removed))
        flash(ngettext("%(num)s audit entry removed.", "%(num)s audit entries removed.", removed), "info")
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/backups", methods=["POST"])
@admin_required
def backup_create():
    from ...core.backup import BackupError
    try:
        path = maintenance.create_backup({**boot_config(), "maintenance": settings()["maintenance"]})
    except (BackupError, OSError) as exc:
        flash(_("The backup failed: %(error)s", error=exc), "error")
    else:
        _audit("backup_created", path.name, "web")
        flash(_("Backup %(name)s created.", name=path.name), "info")
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/backups/<name>")
@admin_required
def backup_download(name: str):
    path = maintenance.backup_path(boot_config(), name)
    if path is None:
        abort(404)
    _audit("backup_downloaded", name)
    return send_file(path, as_attachment=True, download_name=name, mimetype="application/gzip")


@bp.route("/maintenance/backups/<name>/delete", methods=["POST"])
@admin_required
def backup_delete(name: str):
    path = maintenance.backup_path(boot_config(), name)
    if path is None:
        abort(404)
    path.unlink()
    _audit("backup_deleted", name)
    flash(_("Backup %(name)s deleted.", name=name), "info")
    return redirect(url_for("settings.section", name="backups"))


# --------------------------------------------------------------------------- red y HTTPS

FORWARDED_HEADERS = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Forwarded-Port",
                     "X-Forwarded-Prefix")
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def network_context(cfg: dict) -> dict:
    """Cómo ha llegado esta petición y avisos si no cuadra con la configuración."""
    boot = boot_config()
    server, public = boot["server"], cfg["network"]["public_url"]
    behind_proxy, cookie_secure = server["behind_proxy"], boot["session"]["cookie_secure"]
    headers = {h: request.headers.get(h, "") for h in FORWARDED_HEADERS}
    orig = request.environ.get("werkzeug.proxy_fix.orig", {})
    seen = {"scheme": request.scheme, "host": request.host, "prefix": request.script_root or "/",
            "client": request.remote_addr or "", "peer": orig.get("REMOTE_ADDR") or request.remote_addr or "",
            "base": request.host_url.rstrip("/") + request.script_root}
    pub = urlsplit(public) if public else None
    notes: list[tuple[str, str]] = []  # (nivel: ok | info | warn | danger, texto)

    if any(headers.values()) and not behind_proxy:
        notes.append(("warn", _("The request carries X-Forwarded-* headers but server.behind_proxy is disabled: they "
                                "are ignored, so the client address and the scheme are those of the proxy.")))
    if behind_proxy and not headers["X-Forwarded-For"]:
        level = "danger" if server["host"] not in LOOPBACK else "warn"
        notes.append((level, _("server.behind_proxy is enabled but this request has no X-Forwarded-For: it did not "
                               "go through the proxy.")
                      + (" " + _("The service listens on %(host)s, so anyone who reaches it directly can fake their "
                                 "address. Listen on 127.0.0.1.", host=server["host"]) if level == "danger" else "")))
    if not public:
        notes.append(("info", _("There is no public address: external URLs use the host of each request (%(base)s "
                                "now). Set it if users can arrive through more than one name.", base=seen["base"])))
    else:
        if pub.scheme == "https" and request.scheme != "https":
            notes.append(("warn", _("The public address is HTTPS but the application sees this request as HTTP: the "
                                    "proxy does not send X-Forwarded-Proto or server.behind_proxy is disabled.")))
        if pub.netloc.lower() != request.host.lower():
            notes.append(("info", _("You are using %(host)s; the public address is %(public)s.", host=request.host,
                                    public=public)))
        if pub.scheme == "http" and pub.hostname not in LOOPBACK:
            notes.append(("warn", _("The public address is not HTTPS: Entra ID only accepts HTTPS return addresses "
                                    "and passwords travel in clear text.")))
    if cookie_secure and request.scheme != "https" and not public:
        notes.append(("warn", _("The session cookie is HTTPS-only but the application sees this request as HTTP: "
                                "the proxy probably does not send X-Forwarded-Proto. Generated URLs will be http://.")))
    if not cookie_secure and (request.scheme == "https" or (pub and pub.scheme == "https")):
        notes.append(("warn", _("session.cookie_secure is disabled: enable it in production (config.json).")))
    redirect_uri = cfg["auth"]["entra"].get("redirect_uri")
    if redirect_uri and public and not redirect_uri.startswith(public + "/"):
        notes.append(("warn", _("The Entra ID redirect URI (%(uri)s) does not use the public address.",
                                uri=redirect_uri)))
    if not any(level in ("warn", "danger") for level, _text in notes):
        notes.insert(0, ("ok", _("The proxy, the scheme and the public address match.")))

    target = pub or urlsplit(seen["base"])
    return {"seen": seen, "forwarded": headers, "notes": notes,
            "boot_server": server, "cookie_secure": cookie_secure,
            "example": {"host": target.hostname or "files.example.com", "prefix": (target.path or "").rstrip("/"),
                        "upstream": f"{'127.0.0.1' if server['host'] in ('0.0.0.0', '::') else server['host']}"
                                    f":{server['port']}",
                        "body_mb": server["max_upload_mb"] + 16}}


# --------------------------------------------------------------------------- Entra ID: prueba y asistente

def _redirect_uri(ecfg: dict) -> str:
    return ecfg.get("redirect_uri") or external_url("auth.entra_callback")


def _run_check() -> dict:
    ecfg = settings()["auth"]["entra"]
    result = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "results": entra_check.check(ecfg, _redirect_uri(ecfg))}
    session["entra_check"] = result
    return result


@bp.route("/entra/test", methods=["POST"])
@admin_required
def entra_test():
    result = _run_check()
    ok = entra_check.summary(result["results"])
    flash(_("Connection with Entra ID checked: everything is correct.") if ok else
          _("Connection with Entra ID checked: there are problems, see the details."), "info" if ok else "error")
    target = request.form.get("next")
    return redirect(safe_next(target) if target else url_for("settings.section", name="auth"))


@bp.route("/entra/setup", methods=["GET", "POST"])
@admin_required
def entra_setup():
    step = request.values.get("step", 1, type=int)
    step = step if step in WIZARD_STEPS else 1
    error = None
    if request.method == "POST":
        f = request.form
        if step == 2:
            draft, error = save_partial(lambda: {"auth": {"entra": _entra_connection()}})
        elif step == 3:
            def _users():
                mappings = dict(settings()["auth"]["entra"]["role_mappings"])
                admin_group = f.get("admin_group", "").strip()
                if admin_group:
                    mappings[admin_group.lower()] = "admin"
                return {"auth": {"entra": {"auto_provision": f.get("provisioning") == "auto",
                                           "allowed_groups": _split(f.get("allowed_groups", "")),
                                           "default_role": f.get("default_role", "user"),
                                           "role_mappings": mappings}}}
            draft, error = save_partial(_users)
        elif step == 4:
            draft, error = save_partial(lambda: {"auth": {"entra": {"enabled": True}}})
            if not error:
                _audit("settings_updated", None, "entra_setup")
                flash(_("Entra ID enabled. Users can now sign in with Microsoft."), "info")
                return redirect(url_for("settings.section", name="auth"))
        if not error:
            _audit("settings_updated", None, f"entra_setup:{step}")
            return redirect(url_for("settings.entra_setup", step=step + 1))
    ecfg = settings()["auth"]["entra"]
    check = None
    if step == 4 and request.method == "GET" and ecfg.get("tenant_id") and ecfg.get("client_id"):
        check = _run_check()
    registered = session.pop("entra_registered", None) if step == 4 else None
    return render_template("admin/settings/entra_setup.html", step=step, steps=WIZARD_STEPS, en=ecfg,
                           registered=registered,
                           redirect_uri=_redirect_uri(ecfg), error=error, error_field=error.field if error else None,
                           check=check, check_ok=entra_check.summary(check["results"]) if check else None,
                           secret_set=bool(ecfg.get("client_secret")), ROLES=ROLES, ROLE_LABELS=ROLE_LABELS,
                           admin_group=next((k for k, v in ecfg["role_mappings"].items() if v == "admin"), "")), \
        400 if error else 200


# --------------------------------------------------------------------------- Entra ID: registro automático

# Inicios de sesión con código de dispositivo en curso. En memoria del proceso a propósito: el
# device_code no sale del servidor (la sesión solo guarda una clave aleatoria) y un reinicio los
# descarta, que es lo esperable para algo que caduca en 15 minutos.
_FLOWS: dict[str, dict] = {}
_FLOWS_LOCK = threading.Lock()
SLOW_DOWN_STEP, MAX_INTERVAL = 5, 30


def _register_flow() -> tuple[str | None, dict | None]:
    key = session.get("entra_register")
    with _FLOWS_LOCK:
        for k in [k for k, f in _FLOWS.items() if time.time() > f["expires_at"]]:
            _FLOWS.pop(k, None)
        flow = _FLOWS.get(key) if key else None
    if flow and flow["user_id"] != g.user["id"]:
        flow = None
    return key, flow


def _drop_flow(key: str | None) -> None:
    with _FLOWS_LOCK:
        _FLOWS.pop(key, None)
    session.pop("entra_register", None)


def _register_target() -> tuple[str, bool]:
    """Redirect URI que se registrará y si Entra ID la aceptará (HTTPS o localhost)."""
    uri = external_url("auth.entra_callback")
    parts = urlsplit(uri)
    return uri, parts.scheme == "https" or parts.hostname in LOOPBACK


@bp.route("/entra/register", methods=["GET", "POST"])
@admin_required
def entra_register_page():
    redirect_uri, https_ok = _register_target()
    key, flow = _register_flow()
    if request.method == "POST":
        if not https_ok:
            flash(_("Entra ID only accepts HTTPS return addresses: set the public name in Network and HTTPS."),
                  "error")
            return redirect(url_for("settings.entra_register_page"))
        options = {"name": request.form.get("app_name", "").strip() or settings()["app_name"],
                   "redirect_uri": redirect_uri, "logout_url": external_url("auth.login"),
                   "app_roles": _on("app_roles"), "group_claims": _on("group_claims"),
                   "require_assignment": _on("require_assignment"), "group_read": _on("group_read")}
        return _start_flow("register", options)
    return render_template("admin/settings/entra_register.html", flow=flow, redirect_uri=redirect_uri,
                           https_ok=https_ok, app_name=settings()["app_name"],
                           expires_in=int(flow["expires_at"] - time.time()) if flow else 0)


def _start_flow(kind: str, options: dict):
    """Pide un código de dispositivo y aparca el flujo (``register``, ``rotate`` o ``grant_groups``)."""
    key, _flow = _register_flow()
    try:
        code = entra_register.device_start()
    except entra_register.RegisterError as exc:
        flash(_("Could not start the sign-in with Microsoft: %(error)s", error=exc), "error")
        return redirect(url_for("settings.section", name="auth") if kind != "register"
                        else url_for("settings.entra_register_page"))
    _drop_flow(key)
    key = secrets.token_urlsafe(16)
    with _FLOWS_LOCK:
        _FLOWS[key] = {"kind": kind, "device_code": code["device_code"], "user_code": code["user_code"],
                       "verification_uri": code.get("verification_uri", "https://microsoft.com/devicelogin"),
                       "expires_at": time.time() + int(code.get("expires_in", 900)),
                       "interval": int(code.get("interval", 5)), "options": options, "user_id": g.user["id"]}
    session["entra_register"] = key
    return redirect(url_for("settings.entra_register_page"))


def _existing_client_id() -> str:
    client_id = settings()["auth"]["entra"].get("client_id", "")
    if not client_id:
        abort(400, description=_("There is no Client ID configured."))
    return client_id


@bp.route("/entra/rotate", methods=["POST"])
@admin_required
def entra_rotate():
    return _start_flow("rotate", {"client_id": _existing_client_id()})


@bp.route("/entra/grant-groups", methods=["POST"])
@admin_required
def entra_grant_groups():
    return _start_flow("grant_groups", {"client_id": _existing_client_id()})


@bp.route("/entra/register/cancel", methods=["POST"])
@admin_required
def entra_register_cancel():
    key, _flow = _register_flow()
    _drop_flow(key)
    return redirect(url_for("settings.entra_register_page"))


@bp.route("/entra/register/poll", methods=["POST"])
@admin_required
def entra_register_poll():
    """Comprueba si el administrador ya inició sesión; si es así, registra la aplicación.

    Con ``Accept: application/json`` (el JavaScript de la página) devuelve el estado; sin él (el
    botón «Ya he iniciado sesión») redirige.
    """
    wants_json = request.accept_mimetypes.best == "application/json"

    def answer(status: str, message: str = "", target: str | None = None, interval: int | None = None):
        if wants_json:
            return jsonify(status=status, message=message, redirect=target, interval=interval)
        if message:
            flash(message, "info" if status in ("pending", "complete") else "error")
        return redirect(target or url_for("settings.entra_register_page"))

    key, flow = _register_flow()
    if not flow:
        return answer("expired", _("The sign-in code has expired or was cancelled. Start again."))
    try:
        body = entra_register.device_poll(flow["device_code"])
    except entra_register.RegisterError as exc:
        return answer("pending", str(exc), interval=flow["interval"])
    error = body.get("error", "")
    if error == "authorization_pending":
        return answer("pending", "" if wants_json else _("Microsoft has not confirmed the sign-in yet."),
                      interval=flow["interval"])
    if error == "slow_down":
        flow["interval"] = min(flow["interval"] + SLOW_DOWN_STEP, MAX_INTERVAL)
        return answer("pending", interval=flow["interval"])
    _drop_flow(key)  # un código canjeado (o rechazado) no se reutiliza
    if error:
        message = _("Microsoft refused the sign-in: %(error)s", error=entra_register._message(body) or error)
        _audit("entra_app_register_failed", None, error)
        return answer("error", message)

    options, kind = flow["options"], flow.get("kind", "register")
    token = body["access_token"]
    if kind == "rotate":
        try:
            result = entra_register.rotate_secret(token, options["client_id"])
        except entra_register.RegisterError as exc:
            _audit("entra_app_register_failed", options["client_id"], f"rotate:{exc}"[:200])
            return answer("error", _("The secret could not be renewed: %(error)s", error=exc))
        _draft, save_error = save_partial(lambda: {"auth": {"entra": {"client_secret": result["client_secret"],
                                                               "secret_expires": result["secret_expires"]}}})
        if save_error:
            return answer("error", str(save_error))
        session.pop("entra_check", None)
        _audit("entra_secret_rotated", options["client_id"], result["secret_expires"])
        return answer("complete", _("New client secret created and saved. The previous one keeps working until it "
                                    "expires."), url_for("settings.section", name="auth"))
    if kind == "grant_groups":
        try:
            entra_register.grant_group_read(token, options["client_id"])
        except entra_register.RegisterError as exc:
            _audit("entra_app_register_failed", options["client_id"], f"groups:{exc}"[:200])
            return answer("error", _("Reading groups could not be granted: %(error)s", error=exc))
        session.pop("entra_check", None)
        _audit("entra_groups_granted", options["client_id"])
        return answer("complete", _("The application can now read group names (it may take a minute)."),
                      url_for("settings.section", name="auth"))

    try:
        result = entra_register.register_app(token, **options)
    except entra_register.RegisterError as exc:
        _audit("entra_app_register_failed", None, str(exc)[:200])
        return answer("error", _("The application could not be registered: %(error)s", error=exc))

    def _entra_fields():
        mappings = dict(settings()["auth"]["entra"]["role_mappings"])
        if result["app_roles"]:
            mappings[entra_register.ADMIN_ROLE.lower()] = "admin"
        return {"auth": {"entra": {"tenant_id": result["tenant_id"], "client_id": result["client_id"],
                                   "client_secret": result["client_secret"], "secret_expires": result["secret_expires"],
                                   "redirect_uri": options["redirect_uri"], "role_mappings": mappings}}}
    _draft, save_error = save_partial(_entra_fields)
    if save_error:
        return answer("error", _("The application was created in Entra ID (%(client)s) but the settings could not "
                                 "be saved: %(error)s", client=result["client_id"], error=save_error))
    _audit("entra_app_registered", result["client_id"], result["tenant_id"])
    session["entra_registered"] = {"client_id": result["client_id"], "portal_url": result["portal_url"],
                                   "secret_expires": result["secret_expires"], "warnings": result["warnings"]}
    return answer("complete", _("Application registered in Entra ID and saved."),
                  url_for("settings.entra_setup", step=4))

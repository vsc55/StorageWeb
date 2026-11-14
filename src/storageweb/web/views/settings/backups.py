"""Copias de seguridad y base de datos (Sistema → Copias y base de datos)."""
from __future__ import annotations

from flask import abort, flash, redirect, send_file, url_for

from ....core import maintenance
from ....core.backup import BackupError
from ....i18n import _, format_size, ngettext
from ...context import boot_config, get_db, settings
from ...guards import admin_required, audit_event
from . import bp


# --------------------------------------------------------------------------- mantenimiento

@bp.route("/maintenance/vacuum", methods=["POST"])
@admin_required
def maintenance_vacuum():
    before, after = maintenance.vacuum(get_db(), boot_config()["database"])
    audit_event("db_vacuum", None, f"{before}->{after}")
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
        audit_event("audit_purged", None, str(removed))
        flash(ngettext("%(num)s audit entry removed.", "%(num)s audit entries removed.", removed), "info")
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/backups", methods=["POST"])
@admin_required
def backup_create():
    try:
        path = maintenance.create_backup({**boot_config(), "maintenance": settings()["maintenance"]})
    except (BackupError, OSError) as exc:
        flash(_("The backup failed: %(error)s", error=exc), "error")
    else:
        audit_event("backup_created", path.name, "web")
        flash(_("Backup %(name)s created.", name=path.name), "info")
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/backups/<name>")
@admin_required
def backup_download(name: str):
    path = maintenance.backup_path(boot_config(), name)
    if path is None:
        abort(404)
    audit_event("backup_downloaded", name)
    return send_file(path, as_attachment=True, download_name=name, mimetype="application/gzip")


@bp.route("/maintenance/backups/<name>/delete", methods=["POST"])
@admin_required
def backup_delete(name: str):
    path = maintenance.backup_path(boot_config(), name)
    if path is None:
        abort(404)
    path.unlink()
    audit_event("backup_deleted", name)
    flash(_("Backup %(name)s deleted.", name=name), "info")
    return redirect(url_for("settings.section", name="backups"))

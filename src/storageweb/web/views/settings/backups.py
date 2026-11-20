"""Copias de seguridad y base de datos (Sistema → Copias y base de datos)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

from .... import providers, siem
from ....core import backends, backup, ipban, maintenance, monitoring, offsite, quota
from ....core.backup import BackupError
from ....core.permissions import ADMIN
from ....db import connect, schema_version
from ....db.repositories import users
from ....i18n import _, _l, format_size, ngettext
from ...context import boot_config, close_db, get_db, invalidate_settings, settings
from ...guards import admin_required, audit_event, clear_session, client_ip, start_session
from ... import search
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
        _send_offsite(path)
    return redirect(url_for("settings.section", name="backups"))


def _send_offsite(path: Path) -> None:
    """Envía la copia fuera del servidor si está configurado, y dice cómo fue."""
    if not offsite.enabled(settings()):
        return
    error = maintenance.send_offsite(get_db(), settings(), path, g.user["username"])
    if error:
        flash(_("It could not be sent outside the server: %(error)s", error=error), "error")
    else:
        flash(_("Also sent to %(where)s.", where=offsite.where(settings())), "info")


@bp.route("/maintenance/audit-forward/test", methods=["POST"])
@admin_required
def audit_forward_test():
    """Envía un evento de prueba al syslog o al fichero de ``audit.*`` (los ajustes guardados), sin la cola."""
    options = settings()["audit"]
    if not (options["syslog"] or options["file"]):
        flash(_("Set a syslog address or a file first."), "error")
    else:
        error = siem.FORWARDER.test(options)
        audit_event("audit_forward_test", options["syslog"] or options["file"], error or "ok")
        if error:
            flash(_("The test event could not be sent: %(error)s", error=error), "error")
        else:
            flash(_("Test event sent. Look for «audit_forward_test» in the SIEM or in the file."), "info")
    return redirect(url_for("settings.section", name="audit_settings") + "#siem-title")


@bp.route("/maintenance/backups/<name>/offsite", methods=["POST"])
@admin_required
def backup_send(name: str):
    """Envía otra vez una copia de este servidor a la ubicación externa (p. ej. tras un fallo)."""
    path = maintenance.backup_path(boot_config(), name)
    if path is None or not offsite.enabled(settings()):
        abort(404)
    _send_offsite(path)
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/backups/offsite/fetch", methods=["POST"])
@admin_required
def backup_fetch():
    """Trae una copia de la ubicación externa a este servidor, para restaurarla desde la lista."""
    if not offsite.enabled(settings()):
        abort(404)
    name = request.form.get("name", "")
    try:
        path = offsite.fetch(settings(), name, maintenance.backup_dir(boot_config()))
    except (BackupError, OSError) as exc:
        flash(_("The backup could not be brought: %(error)s", error=exc), "error")
        return redirect(url_for("settings.section", name="backups", remote=1) + "#offsite")
    audit_event("backup_fetched", path.name, offsite.where(settings()))
    flash(_("Backup %(name)s brought to this server. You can restore it from the list.", name=path.name), "info")
    return redirect(url_for("settings.section", name="backups"))


@bp.route("/maintenance/backups/<name>")
@admin_required
def backup_download(name: str):
    path = maintenance.backup_path(boot_config(), name)
    if path is None:
        abort(404)
    audit_event("backup_downloaded", name)
    return send_file(path, as_attachment=True, download_name=name, mimetype="application/gzip")


RESTORE_WORD = _l("RESTORE")  # lo que hay que escribir para confirmar


@bp.route("/maintenance/backups/upload", methods=["POST"])
@admin_required
def backup_upload():
    """Sube una copia (de este u otro servidor) a la lista, para poder restaurarla."""
    item = request.files.get("backup")
    if not item or not item.filename:
        flash(_("Choose a backup file (.tar.gz)."), "error")
        return redirect(url_for("settings.section", name="backups"))
    folder = maintenance.backup_dir(boot_config())
    folder.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".subida-", suffix=".part")
    os.close(handle)
    try:
        item.save(tmp)
        path = maintenance.add_backup(boot_config(), Path(tmp), item.filename)
    except (BackupError, OSError) as exc:
        flash(_("The file is not a valid backup: %(error)s", error=exc), "error")
        return redirect(url_for("settings.section", name="backups"))
    finally:
        Path(tmp).unlink(missing_ok=True)
    audit_event("backup_uploaded", path.name, str(path.stat().st_size))
    flash(_("Backup %(name)s uploaded. You can restore it from the list.", name=path.name), "info")
    return redirect(url_for("settings.section", name="backups"))


def _forget_caches() -> None:
    """Lo que el proceso guarda en memoria de la base de datos anterior."""
    invalidate_settings()
    quota.clear()
    ipban.invalidate()
    backends.clear_clients()
    monitoring.reset()
    for method in providers.methods():  # p. ej. los nombres de grupos de Entra ID
        found = method.directory(method.section(settings()))
        if found is not None:
            found.clear_cache()


@bp.route("/maintenance/backups/<name>/restore", methods=["GET", "POST"])
@admin_required
def backup_restore(name: str):
    """Restaurar una copia con el servicio en marcha (con confirmación fuerte): ver ``maintenance.restore_backup``."""
    boot = boot_config()
    path = maintenance.backup_path(boot, name)
    if path is None:
        abort(404)
    try:
        manifest, problem = backup.check_restorable(path), None
    except BackupError as exc:
        manifest, problem = None, str(exc)
    if request.method == "POST" and problem is None:
        typed = request.form.get("confirm", "").strip().upper()
        if typed not in {str(RESTORE_WORD).upper(), "RESTORE"}:
            flash(_("Type %(word)s to confirm.", word=RESTORE_WORD), "error")
        else:
            me = dict(g.user)
            close_db()  # la conexión de esta petición no se queda abierta mientras se sustituye la base de datos
            try:
                result = maintenance.restore_backup(lambda: connect(boot["database"]), boot, name,
                                                    actor=me["username"], ip=client_ip())
            except BackupError as exc:
                flash(_("The backup could not be restored: %(error)s", error=exc), "error")
                return redirect(url_for("settings.backup_restore", name=name))
            _forget_caches()
            back = users.get_by_id(get_db(), me["id"])
            message = _("Backup %(name)s restored. The previous state was saved as %(safety)s, in case you need to "
                        "go back. Everyone has to sign in again.", name=name, safety=result["safety"])
            if back is not None and back["username"] == me["username"] and back["enabled"] and back["role"] == ADMIN:
                start_session(back)  # quien restaura sigue dentro si su cuenta está en la copia
                flash(message, "info")
                return redirect(url_for("settings.section", name="backups"))
            clear_session()
            flash(message, "info")
            return redirect(url_for("auth.login", manual=1))
    return render_template("admin/settings/backup_restore.html", name=name, manifest=manifest, problem=problem,
                           current_schema=schema_version(get_db()), word=RESTORE_WORD), (400 if problem else 200)


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


search.action("download", _l("Create a backup now"), "settings.section", {"name": "backups"}, "backups",
              "copia seguridad backup ahora", order=40)
search.action("upload", _l("Restore a backup"), "settings.section", {"name": "backups"}, "backups",
              "restaurar copia seguridad backup restore recuperar", order=41)
search.action("sync", _l("Compact the database"), "settings.section", {"name": "backups"},
              words="base datos compactar vacuum", order=100)

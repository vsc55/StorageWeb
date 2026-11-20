"""Copias de seguridad: crear, listar y restaurar."""
from __future__ import annotations

import sys
from pathlib import Path

from ..db import connect
from ..db.repositories import audit
from ..i18n import _, _l
from ..settings import ConfigError, load_config
from .common import _fail, command


def _backup_dir(cfg, args) -> Path:
    return Path(args.output) if args.output else Path(cfg["data_dir"]) / "backups"


def _backup_args(p):
    p.add_argument("--output", help=_("Destination folder (default <data_dir>/backups)"))
    p.add_argument("--keep", type=int, help=_("Keep only the N most recent backups in the folder"))
    p.add_argument("--no-offsite", action="store_true",
                   help=_("Do not send it outside the server even if maintenance.offsite_location is set"))


@command("backup", _l("Back up the database, config.json and secret_key"), _backup_args, order=140)
def cmd_backup(cfg, conn, args):
    from ..core import backup, maintenance
    from ..settings.runtime import open_runtime

    try:
        path = backup.create(cfg, _backup_dir(cfg, args), keep=args.keep)
    except backup.BackupError as exc:
        _fail(_("Error: %(error)s", error=exc))
    audit.log(conn, "backup", str(path), username="cli")
    print(path)
    if args.no_offsite:
        return
    # La ubicación puede estar elegida desde la web: con los ajustes efectivos, no solo config.json
    runtime, _boot = open_runtime(args.config, create_key=False)
    error = maintenance.send_offsite(conn, runtime.current(conn), path, "cli")
    if error:
        _fail(_("The backup was made, but it could not be sent outside the server: %(error)s", error=error))


def _backup_list_args(p):
    p.add_argument("--output", help=_("Backup folder (default <data_dir>/backups)"))


@command("backup-list", _l("List the backups in a folder"), _backup_list_args, order=141)
def cmd_backup_list(cfg, conn, args):
    from ..core import backup

    for path in backup.list_backups(_backup_dir(cfg, args)):
        try:
            m = backup.read_manifest(path)
            print(_("%(path)s  %(date)s  v%(version)s  schema %(schema)s", path=path, date=m["created_at"],
                    version=m["storageweb_version"], schema=m["schema_version"]))
        except backup.BackupError as exc:
            print(_("%(path)s  (not valid: %(error)s)", path=path, error=exc))


def _restore_args(p):
    p.add_argument("archive", help=_("storageweb-backup-*.tar.gz file"))
    p.add_argument("--force", action="store_true",
                   help=_("Replace the existing database (a copy .antes-de-restaurar-* is kept first)"))
    p.add_argument("--config-to", help=_("Write the config.json from the backup to this path"))


@command("restore", _l("Restore a backup (with the service stopped)"), _restore_args, needs_db=False, order=142)
def cmd_restore(args) -> int:
    """Se ejecuta sin abrir antes la base de datos (podría no existir o estar dañada)."""
    from ..core import backup

    try:
        cfg = load_config(args.config)
        manifest = backup.restore(cfg, Path(args.archive), force=args.force,
                                  config_to=Path(args.config_to) if args.config_to else None)
    except (ConfigError, backup.BackupError) as exc:
        print(_("Error: %(error)s", error=exc), file=sys.stderr)
        return 1
    conn = connect(cfg["database"])
    try:
        audit.log(conn, "restore", args.archive, username="cli",
                  detail=f"{manifest['created_at']} (v{manifest['storageweb_version']})")
    finally:
        conn.close()
    print(_("Restored the backup from %(date)s (StorageWeb %(version)s, schema %(old)s -> %(new)s).",
            date=manifest["created_at"], version=manifest["storageweb_version"],
            old=manifest["schema_version"], new=manifest["restored_schema_version"]))
    if args.config_to:
        print(_("config.json from the backup saved to %(path)s", path=args.config_to))
    return 0

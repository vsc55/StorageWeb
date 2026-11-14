"""Copias de seguridad: crear, listar y restaurar."""
from __future__ import annotations

import sys
from pathlib import Path

from ..db import connect
from ..db.repositories import audit
from ..i18n import _
from ..settings import ConfigError, load_config
from .common import _fail


def _backup_dir(cfg, args) -> Path:
    return Path(args.output) if args.output else Path(cfg["data_dir"]) / "backups"


def cmd_backup(cfg, conn, args):
    from ..core import backup

    try:
        path = backup.create(cfg, _backup_dir(cfg, args), keep=args.keep)
    except backup.BackupError as exc:
        _fail(_("Error: %(error)s", error=exc))
    audit.log(conn, "backup", str(path), username="cli")
    print(path)


def cmd_backup_list(cfg, conn, args):
    from ..core import backup

    for path in backup.list_backups(_backup_dir(cfg, args)):
        try:
            m = backup.read_manifest(path)
            print(_("%(path)s  %(date)s  v%(version)s  schema %(schema)s", path=path, date=m["created_at"],
                    version=m["storageweb_version"], schema=m["schema_version"]))
        except backup.BackupError as exc:
            print(_("%(path)s  (not valid: %(error)s)", path=path, error=exc))


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

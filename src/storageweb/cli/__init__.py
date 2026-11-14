"""Línea de comandos de StorageWeb: servidor y administración.

    storageweb serve [--dev] [--host H] [--port P]   arranca el servidor
    storageweb user-add admin --role admin           crea un usuario
    storageweb --help                                lista todos los comandos

En el servidor ejecútala con el usuario del servicio: ``sudo storageweb-admin <comando>``.
El idioma de los mensajes sale de STORAGEWEB_LANG, LC_ALL, LC_MESSAGES o LANG (es | en).

Un módulo por grupo de comandos (``server``, ``users``, ``config``, ``security``, ``backup``); aquí, los
argumentos y el reparto.
"""
from __future__ import annotations

import argparse
import sys

from .. import i18n
from ..db import connect, init_db
from ..i18n import _
from ..settings import ROLES, ConfigError, load_config
from . import backup, config, security, server, users

# Comandos que trabajan sobre la configuración y la base de datos: (cfg, conn, args)
COMMANDS = {
    "user-add": users.cmd_user_add,
    "user-passwd": users.cmd_user_passwd,
    "user-set": users.cmd_user_set,
    "user-del": users.cmd_user_del,
    "user-exists": users.cmd_user_exists,
    "user-list": users.cmd_user_list,
    "init-db": config.cmd_init_db,
    "audit": config.cmd_audit,
    "check-config": config.cmd_check_config,
    "settings-reset": config.cmd_settings_reset,
    "ip-list": security.cmd_ip_list,
    "ip-unban": security.cmd_ip_unban,
    "ip-allow": security.cmd_ip_allow,
    "sessions-close": security.cmd_sessions_close,
    "backup": backup.cmd_backup,
    "backup-list": backup.cmd_backup_list,
}


def build_parser() -> argparse.ArgumentParser:
    """Los textos de ayuda se traducen al construir el parser (idioma activo en ese momento)."""
    parser = argparse.ArgumentParser(prog="storageweb", description=_("StorageWeb: server and administration"))
    parser.add_argument("--config", metavar=_("PATH"),
                        help=_("Path to config.json (default $STORAGEWEB_CONFIG, then /etc/storageweb/config.json)"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help=_("Start the web server"))
    p.add_argument("--host", help=_("Overrides server.host"))
    p.add_argument("--port", type=int, help=_("Overrides server.port"))
    p.add_argument("--dev", action="store_true", help=_("Development: debugger and automatic reload"))
    p.add_argument("--no-reload", action="store_true", help=_("With --dev, without reload (for debugging)"))

    sub.add_parser("init-db", help=_("Create the database or apply pending migrations"))

    p = sub.add_parser("user-add", help=_("Create a user (local by default)"))
    p.add_argument("username", help=_("User name (for Entra ID, the UPN: juan@contoso.com)"))
    p.add_argument("--source", choices=("local", "entra"), default="local",
                   help=_("'entra' = register an Entra ID user beforehand (no password)"))
    p.add_argument("--role", choices=ROLES, default="user", help=_("Role of the user"))
    p.add_argument("--password", help=_("Password (avoid it: it stays in the shell history; better let it ask)"))
    p.add_argument("--password-stdin", action="store_true", help=_("Read the password from standard input"))
    p.add_argument("--name", help=_("Display name"))
    p.add_argument("--email", help=_("Email address"))
    p.add_argument("--groups", help=_("Comma-separated groups (they give access to shared folders)"))
    p.add_argument("--home", help=_("Custom personal folder (default storage.home_template)"))

    p = sub.add_parser("user-passwd", help=_("Change the password of a local user"))
    p.add_argument("username", help=_("User name"))
    p.add_argument("--password", help=_("New password (asked if omitted)"))
    p.add_argument("--password-stdin", action="store_true", help=_("Read the password from standard input"))

    p = sub.add_parser("user-set", help=_("Change the role, groups, folder, language or status of a user"))
    p.add_argument("username", help=_("User name"))
    p.add_argument("--role", choices=ROLES, help=_("New role"))
    p.add_argument("--groups", help=_("Comma-separated groups (replace the current ones)"))
    p.add_argument("--home", help=_("Personal folder; '' to go back to storage.home_template"))
    p.add_argument("--name", help=_("Display name"))
    p.add_argument("--email", help=_("Email address"))
    p.add_argument("--locale", choices=i18n.LOCALES, help=_("Preferred interface language"))
    g = p.add_mutually_exclusive_group()
    g.add_argument("--enable", action="store_true", help=_("Enable the account"))
    g.add_argument("--disable", action="store_true", help=_("Disable the account"))

    p = sub.add_parser("user-del", help=_("Delete a user (their files are not removed)"))
    p.add_argument("username", help=_("User name"))

    sub.add_parser("user-list", help=_("List users"))

    p = sub.add_parser("user-exists", help=_("Exit code 0 if the user exists, 1 if not"))
    p.add_argument("username", help=_("User name"))

    p = sub.add_parser("audit", help=_("Show the audit log"))
    p.add_argument("--limit", type=int, default=50, help=_("Maximum number of entries"))
    p.add_argument("--user", help=_("Filter by user"))

    sub.add_parser("check-config", help=_("Validate the configuration and warn if there is no administrator"))

    sub.add_parser("settings-reset", help=_("Discard the settings saved from the web and go back to the default values"))

    sub.add_parser("ip-list", help=_("List blocked and allowed IP addresses"))
    p = sub.add_parser("ip-unban", help=_("Unblock an IP address or network (rescue if you blocked yourself)"))
    p.add_argument("network", nargs="?", help=_("IP address or network (CIDR)"))
    p.add_argument("--all", action="store_true", help=_("Remove every block"))
    p = sub.add_parser("ip-allow", help=_("Add an IP address or network to the allow list (never blocked)"))
    p.add_argument("network", help=_("IP address or network (CIDR)"))
    p.add_argument("--reason", help=_("Note"))
    p = sub.add_parser("sessions-close", help=_("Close the open sessions of a user (or of everybody)"))
    p.add_argument("username", nargs="?", help=_("User name"))
    p.add_argument("--all", action="store_true", help=_("Close every session"))

    p = sub.add_parser("backup", help=_("Back up the database, config.json and secret_key"))
    p.add_argument("--output", help=_("Destination folder (default <data_dir>/backups)"))
    p.add_argument("--keep", type=int, help=_("Keep only the N most recent backups in the folder"))

    p = sub.add_parser("backup-list", help=_("List the backups in a folder"))
    p.add_argument("--output", help=_("Backup folder (default <data_dir>/backups)"))

    p = sub.add_parser("restore", help=_("Restore a backup (with the service stopped)"))
    p.add_argument("archive", help=_("storageweb-backup-*.tar.gz file"))
    p.add_argument("--force", action="store_true",
                   help=_("Replace the existing database (a copy .antes-de-restaurar-* is kept first)"))
    p.add_argument("--config-to", help=_("Write the config.json from the backup to this path"))
    return parser


def main(argv: list[str] | None = None) -> int:
    token = i18n.set_locale(i18n.from_environment())
    try:
        return _main(argv)
    finally:
        i18n.reset_locale(token)


def _main(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        return server.cmd_serve(args)
    if args.cmd == "restore":
        return backup.cmd_restore(args)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
        return 2
    init_db(cfg["database"])
    conn = connect(cfg["database"])
    try:
        COMMANDS[args.cmd](cfg, conn, args)
    finally:
        conn.close()
    return 0

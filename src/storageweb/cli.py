"""Línea de comandos de StorageWeb: servidor y administración.

    storageweb serve [--dev] [--host H] [--port P]   arranca el servidor
    storageweb user-add admin --role admin           crea un usuario
    storageweb --help                                lista todos los comandos

En el servidor ejecútala con el usuario del servicio: ``sudo storageweb-admin <comando>``.
El idioma de los mensajes sale de STORAGEWEB_LANG, LC_ALL, LC_MESSAGES o LANG (es | en).
"""
from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from . import i18n
from .db import connect, init_db
from .db.repositories import audit, users
from .i18n import _
from .providers import local
from .settings import ROLES, ConfigError, default_config_path, load_config


def _fail(message: str) -> None:
    sys.exit(message)


# --------------------------------------------------------------------------- servidor

def cmd_serve(args) -> int:
    from . import create_app

    try:
        app = create_app(args.config)
    except ConfigError as exc:
        print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
        return 2
    srv = app.config["SW"]["server"]
    host = args.host or srv["host"]
    port = args.port or srv["port"]

    if args.dev:
        cfg_file = Path(args.config) if args.config else default_config_path()
        templates = Path(app.root_path) / app.template_folder
        catalogs = Path(i18n.LOCALE_DIR).rglob("*.po")
        app.run(host=host, port=port, debug=True, use_reloader=not args.no_reload, reloader_type="stat",
                # Además del código Python, reinicia al cambiar la config, las plantillas o las traducciones
                extra_files=[str(cfg_file), *map(str, templates.rglob("*.html")), *map(str, catalogs)])
        return 0

    from waitress import serve

    logging.getLogger("waitress").setLevel(logging.INFO)
    app.logger.info("StorageWeb listening on http://%s:%s (config: %s)", host, port,
                    app.config["SW"]["_config_path"])
    serve(app, host=host, port=port, threads=int(srv["threads"]),
          max_request_body_size=srv["max_upload_mb"] * 1024 * 1024 + 1024 * 1024,
          channel_timeout=300, ident="StorageWeb")
    return 0


# --------------------------------------------------------------------------- administración

def _read_password(args) -> str | None:
    """Contraseña de --password, de --password-stdin o None (se preguntará)."""
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\r\n")
    return args.password


def _prompt_password() -> str:
    password = getpass.getpass(_("Password: "))
    if password != getpass.getpass(_("Repeat the password: ")):
        _fail(_("The passwords do not match."))
    return password


def _ask_password(given: str | None) -> str:
    try:
        return local.hash_password(given or _prompt_password())
    except ValueError as exc:
        _fail(str(exc))


def _groups(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _get(conn, username):
    user = users.get_by_username(conn, username)
    if user is None:
        _fail(_("The user %(name)s does not exist.", name=repr(username)))
    return user


def cmd_init_db(cfg, conn, args):
    print(_("Database ready: %(path)s", path=cfg["database"]))


def cmd_user_add(cfg, conn, args):
    from .core.accounts import AccountError, create_account

    password = None
    if args.source == "local":
        password = _read_password(args) or _prompt_password()
    try:
        create_account(conn, username=args.username, source=args.source, role=args.role,
                       password=password, display_name=args.name, email=args.email,
                       groups=_groups(args.groups), home_path=args.home)
    except AccountError as exc:
        _fail(exc.message)
    print(_("User %(name)s (%(source)s, %(role)s) created.", name=repr(args.username), source=args.source,
            role=args.role))


def cmd_user_passwd(cfg, conn, args):
    user = _get(conn, args.username)
    if user["source"] != "local":
        _fail(_("%(name)s is a %(source)s user; its password is not managed here.",
                name=repr(args.username), source=user["source"]))
    users.update(conn, user["id"], password_hash=_ask_password(_read_password(args)))
    print(_("Password updated."))


def cmd_user_set(cfg, conn, args):
    user = _get(conn, args.username)
    fields = {}
    if args.groups is not None:
        fields["groups"] = _groups(args.groups)
    if args.home is not None:
        fields["home_path"] = args.home
    if args.name is not None:
        fields["display_name"] = args.name
    if args.email is not None:
        fields["email"] = args.email
    if args.role is not None:
        fields["role"] = args.role
    if args.locale is not None:
        fields["locale"] = i18n.normalize(args.locale)
    if args.enable:
        fields["enabled"] = True
    if args.disable:
        fields["enabled"] = False
    if not fields:
        _fail(_("Nothing to change."))
    users.update(conn, user["id"], **fields)
    print(_("User %(name)s updated: %(fields)s", name=repr(args.username), fields=", ".join(fields)))


def cmd_user_del(cfg, conn, args):
    user = _get(conn, args.username)
    users.delete(conn, user["id"])
    print(_("User %(name)s deleted (their files have NOT been removed).", name=repr(args.username)))


def cmd_user_exists(cfg, conn, args):
    sys.exit(0 if users.get_by_username(conn, args.username) else 1)


def cmd_user_list(cfg, conn, args):
    fmt = "{:<32} {:<6} {:<6} {:<4} {:<25} {:<20} {}"
    print(fmt.format(_("USER"), _("SOURCE"), _("ROLE"), _("ON"), _("GROUPS"), _("LAST SIGN-IN"), _("HOME")))
    for r in users.list_all(conn):
        print(fmt.format(r["username"], r["source"], r["role"], _("yes") if r["enabled"] else _("no"),
                         (r["groups"] or "")[:25], (r["last_login"] or "-")[:19],
                         r["home_path"] or _("(template)")))


def cmd_audit(cfg, conn, args):
    for r in audit.recent(conn, args.limit, username=args.user):
        print(f"{r['ts']}  {r['username'] or '-':<25} {r['action']:<16} {r['target'] or '':<40} "
              f"{r['ip'] or ''} {r['detail'] or ''}")


def cmd_check_config(cfg, conn, args):
    a = cfg["auth"]
    rows = [
        (_("Config"), cfg["_config_path"]),
        (_("Database"), cfg["database"]),
        (_("Homes"), cfg["storage"]["home_template"]),
        (_("Language"), cfg["default_locale"]),
        (_("Sign-in"), f"local={a['local']['enabled']} pam={a['pam']['enabled']} "
                       f"entra={a['entra']['enabled']} ({a['entra']['provider']})"),
    ]
    for s in cfg["storage"]["shares"]:
        state = _("OK") if Path(s["path"]).is_dir() else _("MISSING")
        rows.append((_("Share"), f"{s['name']:<15} {s['path']} [{state}] ro={s['read_only']} "
                                 f"users={s['users']} groups={s['groups']}"))
    width = max(len(label) for label, _value in rows) + 2
    for label, value in rows:
        print(f"{label + ':':<{width}}{value}")
    if users.count_admins(conn) == 0:
        print(_("WARNING: there is no administrator. Create one with: user-add <user> --role admin"))
    print(_("Valid configuration."))


def cmd_settings_reset(cfg, conn, args):
    """Vía de rescate si unos ajustes web dejan a todos sin poder entrar."""
    from .db.repositories import settings as settings_repo
    from .settings import RUNTIME_KEY

    settings_repo.put(conn, RUNTIME_KEY, {}, "cli")
    audit.log(conn, "settings_reset", username="cli")
    print(_("Web settings discarded: only config.json applies (the service notices on the next request)."))


# --------------------------------------------------------------------------- copias de seguridad

def _backup_dir(cfg, args) -> Path:
    return Path(args.output) if args.output else Path(cfg["data_dir"]) / "backups"


def cmd_backup(cfg, conn, args):
    from .core import backup

    try:
        path = backup.create(cfg, _backup_dir(cfg, args), keep=args.keep)
    except backup.BackupError as exc:
        _fail(_("Error: %(error)s", error=exc))
    audit.log(conn, "backup", str(path), username="cli")
    print(path)


def cmd_backup_list(cfg, conn, args):
    from .core import backup

    for path in backup.list_backups(_backup_dir(cfg, args)):
        try:
            m = backup.read_manifest(path)
            print(_("%(path)s  %(date)s  v%(version)s  schema %(schema)s", path=path, date=m["created_at"],
                    version=m["storageweb_version"], schema=m["schema_version"]))
        except backup.BackupError as exc:
            print(_("%(path)s  (not valid: %(error)s)", path=path, error=exc))


def cmd_restore(args) -> int:
    """Se ejecuta sin abrir antes la base de datos (podría no existir o estar dañada)."""
    from .core import backup

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


# --------------------------------------------------------------------------- argumentos

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

    sub.add_parser("settings-reset", help=_("Discard the settings saved from the web and go back to config.json"))

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
        return cmd_serve(args)
    if args.cmd == "restore":
        return cmd_restore(args)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
        return 2
    init_db(cfg["database"])
    conn = connect(cfg["database"])
    try:
        globals()["cmd_" + args.cmd.replace("-", "_")](cfg, conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

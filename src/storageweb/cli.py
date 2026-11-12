"""Línea de comandos de StorageWeb: servidor y administración.

    storageweb serve [--dev] [--host H] [--port P]   arranca el servidor
    storageweb user-add admin --role admin           crea un usuario
    storageweb --help                                lista todos los comandos

En el servidor ejecútala con el usuario del servicio: ``sudo storageweb-admin <comando>``.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from .db import connect, init_db
from .db.repositories import audit, users
from .providers import local
from .settings import ROLES, ConfigError, default_config_path, load_config


# --------------------------------------------------------------------------- servidor

def cmd_serve(args) -> int:
    from . import create_app

    try:
        app = create_app(args.config)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2
    srv = app.config["SW"]["server"]
    host = args.host or srv["host"]
    port = args.port or srv["port"]

    if args.dev:
        cfg_file = Path(args.config) if args.config else default_config_path()
        templates = Path(app.root_path) / app.template_folder
        app.run(host=host, port=port, debug=True, use_reloader=not args.no_reload, reloader_type="stat",
                # Además del código Python, reinicia al cambiar la config o las plantillas
                extra_files=[str(cfg_file), *map(str, templates.rglob("*.html"))])
        return 0

    from waitress import serve

    logging.getLogger("waitress").setLevel(logging.INFO)
    app.logger.info("StorageWeb escuchando en http://%s:%s (config: %s)", host, port,
                    app.config["SW"]["_config_path"])
    serve(app, host=host, port=port, threads=int(srv["threads"]),
          max_request_body_size=srv["max_upload_mb"] * 1024 * 1024 + 1024 * 1024,
          channel_timeout=300, ident="StorageWeb")
    return 0


# --------------------------------------------------------------------------- administración

def _ask_password(given: str | None) -> str:
    if given:
        pw = given
    else:
        pw = getpass.getpass("Contraseña: ")
        if pw != getpass.getpass("Repite la contraseña: "):
            sys.exit("Las contraseñas no coinciden.")
    try:
        return local.hash_password(pw)
    except ValueError as exc:
        sys.exit(str(exc))


def _groups(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _get(conn, username):
    user = users.get_by_username(conn, username)
    if user is None:
        sys.exit(f"El usuario '{username}' no existe.")
    return user


def cmd_init_db(cfg, conn, args):
    print(f"Base de datos lista: {cfg['database']}")


def cmd_user_add(cfg, conn, args):
    from .core.accounts import AccountError, create_account

    password = None
    if args.source == "local":
        password = args.password
        if not password:
            password = getpass.getpass("Contraseña: ")
            if password != getpass.getpass("Repite la contraseña: "):
                sys.exit("Las contraseñas no coinciden.")
    try:
        create_account(conn, username=args.username, source=args.source, role=args.role,
                       password=password, display_name=args.name, email=args.email,
                       groups=_groups(args.groups), home_path=args.home)
    except AccountError as exc:
        sys.exit(exc.message)
    print(f"Usuario '{args.username}' ({args.source}, {args.role}) creado.")


def cmd_user_passwd(cfg, conn, args):
    user = _get(conn, args.username)
    if user["source"] != "local":
        sys.exit(f"'{args.username}' es un usuario {user['source']}; su contraseña no se gestiona aquí.")
    users.update(conn, user["id"], password_hash=_ask_password(args.password))
    print("Contraseña actualizada.")


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
    if args.enable:
        fields["enabled"] = True
    if args.disable:
        fields["enabled"] = False
    if not fields:
        sys.exit("Nada que cambiar.")
    users.update(conn, user["id"], **fields)
    print(f"Usuario '{args.username}' actualizado: {', '.join(fields)}")


def cmd_user_del(cfg, conn, args):
    user = _get(conn, args.username)
    users.delete(conn, user["id"])
    print(f"Usuario '{args.username}' eliminado (sus archivos NO se han borrado).")


def cmd_user_list(cfg, conn, args):
    fmt = "{:<32} {:<6} {:<6} {:<4} {:<25} {:<20} {}"
    print(fmt.format("USUARIO", "ORIGEN", "ROL", "ACT", "GRUPOS", "ÚLTIMO LOGIN", "HOME"))
    for r in users.list_all(conn):
        print(fmt.format(r["username"], r["source"], r["role"], "sí" if r["enabled"] else "no",
                         (r["groups"] or "")[:25], (r["last_login"] or "-")[:19],
                         r["home_path"] or "(plantilla)"))


def cmd_audit(cfg, conn, args):
    for r in audit.recent(conn, args.limit, username=args.user):
        print(f"{r['ts']}  {r['username'] or '-':<25} {r['action']:<16} {r['target'] or '':<40} "
              f"{r['ip'] or ''} {r['detail'] or ''}")


def cmd_check_config(cfg, conn, args):
    print(f"Config:   {cfg['_config_path']}")
    print(f"BD:       {cfg['database']}")
    print(f"Homes:    {cfg['storage']['home_template']}")
    a = cfg["auth"]
    print(f"Auth:     local={a['local']['enabled']} pam={a['pam']['enabled']} "
          f"entra={a['entra']['enabled']} ({a['entra']['provider']})")
    for s in cfg["storage"]["shares"]:
        state = "OK" if Path(s["path"]).is_dir() else "NO EXISTE"
        print(f"Share:    {s['name']:<15} {s['path']} [{state}] ro={s['read_only']} "
              f"users={s['users']} groups={s['groups']}")
    if users.count_admins(conn) == 0:
        print("AVISO:    no hay ningún administrador. Crea uno con: user-add <usuario> --role admin")
    print("Configuración válida.")


# --------------------------------------------------------------------------- argumentos

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="storageweb", description="StorageWeb: servidor y administración")
    parser.add_argument("--config", help="Ruta a config.json (por defecto $STORAGEWEB_CONFIG)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="Arranca el servidor web")
    p.add_argument("--host", help="Sobrescribe server.host")
    p.add_argument("--port", type=int, help="Sobrescribe server.port")
    p.add_argument("--dev", action="store_true", help="Desarrollo: depurador y recarga automática")
    p.add_argument("--no-reload", action="store_true", help="Con --dev, sin recarga (para depurar)")

    sub.add_parser("init-db", help="Crea la base de datos o aplica las migraciones pendientes")

    p = sub.add_parser("user-add", help="Crea un usuario (local por defecto)")
    p.add_argument("username")
    p.add_argument("--source", choices=("local", "entra"), default="local",
                   help="'entra' = alta previa de un usuario de Entra ID (sin contraseña)")
    p.add_argument("--role", choices=ROLES, default="user")
    p.add_argument("--password", help="(evítalo: queda en el historial; mejor que lo pregunte)")
    p.add_argument("--name")
    p.add_argument("--email")
    p.add_argument("--groups", help="Lista separada por comas")
    p.add_argument("--home", help="Ruta de home personalizada (por defecto storage.home_template)")

    p = sub.add_parser("user-passwd", help="Cambia la contraseña de un usuario local")
    p.add_argument("username")
    p.add_argument("--password")

    p = sub.add_parser("user-set", help="Modifica rol/grupos/home/estado de un usuario")
    p.add_argument("username")
    p.add_argument("--role", choices=ROLES)
    p.add_argument("--groups")
    p.add_argument("--home", help="'' para volver a la plantilla")
    p.add_argument("--name")
    p.add_argument("--email")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")

    p = sub.add_parser("user-del", help="Elimina un usuario (no borra sus archivos)")
    p.add_argument("username")

    sub.add_parser("user-list", help="Lista usuarios")

    p = sub.add_parser("audit", help="Muestra el registro de auditoría")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--user")

    sub.add_parser("check-config", help="Valida la configuración")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        return cmd_serve(args)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
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

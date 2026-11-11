#!/usr/bin/env python3
"""Administración de StorageWeb por línea de comandos (usuarios, auditoría, comprobación de config).

Ejecutar SIEMPRE con el usuario del servicio para que los ficheros tengan el dueño correcto:
    sudo storageweb-admin user-add admin --role admin
"""
from __future__ import annotations

import argparse
import getpass
import sys

from src import db
from src.config import ConfigError, ROLES, load_config
from src.db import audit, users
from src.providers import local


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
    user = users.get_by_username(username, conn)
    if user is None:
        sys.exit(f"El usuario '{username}' no existe.")
    return user


def cmd_init_db(cfg, conn, args):
    print(f"Base de datos lista: {cfg['database']}")


def cmd_user_add(cfg, conn, args):
    if users.get_by_username(args.username, conn):
        sys.exit(f"El usuario '{args.username}' ya existe.")
    password_hash = _ask_password(args.password) if args.source == "local" else None
    username = args.username.lower() if args.source == "entra" else args.username
    users.create(username=username, source=args.source, role=args.role, password_hash=password_hash,
                 display_name=args.name, email=args.email, groups=_groups(args.groups),
                 home_path=args.home, conn=conn)
    print(f"Usuario '{username}' ({args.source}, {args.role}) creado.")


def cmd_user_passwd(cfg, conn, args):
    user = _get(conn, args.username)
    if user["source"] != "local":
        sys.exit(f"'{args.username}' es un usuario {user['source']}; su contraseña no se gestiona aquí.")
    users.update(user["id"], conn, password_hash=_ask_password(args.password))
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
    users.update(user["id"], conn, **fields)
    print(f"Usuario '{args.username}' actualizado: {', '.join(fields)}")


def cmd_user_del(cfg, conn, args):
    user = _get(conn, args.username)
    users.delete(user["id"], conn)
    print(f"Usuario '{args.username}' eliminado (sus archivos NO se han borrado).")


def cmd_user_list(cfg, conn, args):
    fmt = "{:<32} {:<6} {:<6} {:<4} {:<25} {:<20} {}"
    print(fmt.format("USUARIO", "ORIGEN", "ROL", "ACT", "GRUPOS", "ÚLTIMO LOGIN", "HOME"))
    for r in users.list_all(conn):
        print(fmt.format(r["username"], r["source"], r["role"], "sí" if r["enabled"] else "no",
                         (r["groups"] or "")[:25], (r["last_login"] or "-")[:19],
                         r["home_path"] or "(plantilla)"))


def cmd_audit(cfg, conn, args):
    for r in audit.recent(args.limit, username=args.user, conn=conn):
        print(f"{r['ts']}  {r['username'] or '-':<25} {r['action']:<16} {r['target'] or '':<40} "
              f"{r['ip'] or ''} {r['detail'] or ''}")


def cmd_check_config(cfg, conn, args):
    from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(description="Administración de StorageWeb")
    parser.add_argument("--config", help="Ruta a config.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Crea/actualiza el esquema de la base de datos")

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

    sub.add_parser("check-config", help="Valida config.json")

    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        sys.exit(f"Error de configuración: {exc}")
    db.init_db(cfg["database"])
    conn = db.connect(cfg["database"])
    try:
        globals()["cmd_" + args.cmd.replace("-", "_")](cfg, conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

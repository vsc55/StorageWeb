#!/usr/bin/env python3
"""Administración de StorageWeb (usuarios locales, auditoría, comprobación de config).

Ejecutar SIEMPRE con el usuario del servicio para que los ficheros tengan el dueño correcto:
    sudo -u storageweb /opt/storageweb/venv/bin/python /opt/storageweb/manage.py user-list
(el instalador crea el atajo: sudo storageweb-admin user-list)
"""
import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

from src import db
from src.config import ConfigError, load_config

MIN_PASSWORD = 10


def _ask_password(given: str | None) -> str:
    if given:
        pw = given
    else:
        pw = getpass.getpass("Contraseña: ")
        if pw != getpass.getpass("Repite la contraseña: "):
            sys.exit("Las contraseñas no coinciden.")
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    return generate_password_hash(pw)


def _groups(value: str | None) -> list[str]:
    return [x.strip().lower() for x in (value or "").split(",") if x.strip()]


def _get(conn, username):
    user = db.get_user_by_username(username, conn)
    if user is None:
        sys.exit(f"El usuario '{username}' no existe.")
    return user


def cmd_init_db(cfg, conn, args):
    print(f"Base de datos lista: {cfg['database']}")


def cmd_user_add(cfg, conn, args):
    if db.get_user_by_username(args.username, conn):
        sys.exit(f"El usuario '{args.username}' ya existe.")
    db.create_user(conn, username=args.username, source="local",
                   password_hash=_ask_password(args.password), display_name=args.name,
                   email=args.email, groups=_groups(args.groups), home_path=args.home)
    print(f"Usuario '{args.username}' creado.")


def cmd_user_passwd(cfg, conn, args):
    user = _get(conn, args.username)
    if user["source"] != "local":
        sys.exit(f"'{args.username}' es un usuario {user['source']}; su contraseña no se gestiona aquí.")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (_ask_password(args.password), user["id"]))
    conn.commit()
    print("Contraseña actualizada.")


def cmd_user_set(cfg, conn, args):
    user = _get(conn, args.username)
    updates = {}
    if args.groups is not None:
        updates["groups"] = ",".join(_groups(args.groups))
    if args.home is not None:
        updates["home_path"] = args.home or None
    if args.name is not None:
        updates["display_name"] = args.name
    if args.email is not None:
        updates["email"] = args.email
    if args.enable:
        updates["enabled"] = 1
    if args.disable:
        updates["enabled"] = 0
    if not updates:
        sys.exit("Nada que cambiar.")
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*updates.values(), user["id"]))
    conn.commit()
    print(f"Usuario '{args.username}' actualizado: {', '.join(updates)}")


def cmd_user_del(cfg, conn, args):
    user = _get(conn, args.username)
    conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    conn.commit()
    print(f"Usuario '{args.username}' eliminado (sus archivos NO se han borrado).")


def cmd_user_list(cfg, conn, args):
    rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
    fmt = "{:<32} {:<6} {:<4} {:<25} {:<20} {}"
    print(fmt.format("USUARIO", "ORIGEN", "ACT", "GRUPOS", "ÚLTIMO LOGIN", "HOME"))
    for r in rows:
        print(fmt.format(r["username"], r["source"], "sí" if r["enabled"] else "no",
                         (r["groups"] or "")[:25], (r["last_login"] or "-")[:19], r["home_path"] or "(plantilla)"))


def cmd_audit(cfg, conn, args):
    q, params = "SELECT * FROM audit_log", []
    if args.user:
        q += " WHERE username = ?"
        params.append(args.user)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(args.limit)
    for r in conn.execute(q, params).fetchall():
        print(f"{r['ts']}  {r['username'] or '-':<25} {r['action']:<16} {r['target'] or '':<40} "
              f"{r['ip'] or ''} {r['detail'] or ''}")


def cmd_check_config(cfg, conn, args):
    from pathlib import Path
    print(f"Config:   {cfg['_config_path']}")
    print(f"BD:       {cfg['database']}")
    print(f"Homes:    {cfg['storage']['home_template']}")
    a = cfg["auth"]
    print(f"Auth:     local={a['local']['enabled']} pam={a['pam']['enabled']} entra={a['entra']['enabled']}")
    for s in cfg["storage"]["shares"]:
        p = Path(s["path"])
        state = "OK" if p.is_dir() else "NO EXISTE"
        print(f"Share:    {s['name']:<15} {s['path']} [{state}] ro={s['read_only']} "
              f"users={s['users']} groups={s['groups']}")
    print("Configuración válida.")


def main():
    parser = argparse.ArgumentParser(description="Administración de StorageWeb")
    parser.add_argument("--config", help="Ruta a config.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Crea/actualiza el esquema de la base de datos")

    p = sub.add_parser("user-add", help="Crea un usuario local")
    p.add_argument("username")
    p.add_argument("--password", help="(evítalo: queda en el historial; mejor que lo pregunte)")
    p.add_argument("--name"); p.add_argument("--email")
    p.add_argument("--groups", help="Lista separada por comas")
    p.add_argument("--home", help="Ruta de home personalizada (por defecto storage.home_template)")

    p = sub.add_parser("user-passwd", help="Cambia la contraseña de un usuario local")
    p.add_argument("username"); p.add_argument("--password")

    p = sub.add_parser("user-set", help="Modifica grupos/home/estado de un usuario")
    p.add_argument("username")
    p.add_argument("--groups"); p.add_argument("--home", help="'' para volver a la plantilla")
    p.add_argument("--name"); p.add_argument("--email")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--enable", action="store_true"); g.add_argument("--disable", action="store_true")

    p = sub.add_parser("user-del", help="Elimina un usuario (no borra sus archivos)")
    p.add_argument("username")

    sub.add_parser("user-list", help="Lista usuarios")

    p = sub.add_parser("audit", help="Muestra el registro de auditoría")
    p.add_argument("--limit", type=int, default=50); p.add_argument("--user")

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

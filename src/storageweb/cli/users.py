"""Comandos de usuarios: alta, contraseña, cambios, baja y listados."""
from __future__ import annotations

import sys

from .. import i18n
from ..db.repositories import users
from ..i18n import _
from ..providers import local
from .common import _ask_password, _fail, _get, _groups, _prompt_password, _read_password


def cmd_user_add(cfg, conn, args):
    from ..core.accounts import AccountError, create_account

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
    if not fields and args.groups is None:
        _fail(_("Nothing to change."))
    users.update(conn, user["id"], **fields)
    if args.groups is not None:
        from ..core import groups as group_core

        group_core.set_manual_groups(conn, user["id"], _groups(args.groups))
        fields["groups"] = True
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

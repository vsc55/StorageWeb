"""Comandos de usuarios: alta, contraseña, cambios, baja y listados."""
from __future__ import annotations

import sys

from .. import i18n, providers
from ..db.repositories import audit, users
from ..i18n import _, _l
from ..core.accounts import stores_password
from .common import _fail, _get, _groups, _prompt_password, _read_password, command, effective, password_rules


def _user_add_args(p):
    p.add_argument("username", help=_("User name (for Entra ID, the UPN: juan@contoso.com)"))
    p.add_argument("--source", choices=[m.key for m in providers.methods()], default=None,
                   help=_("Sign-in method of the account (default: the first one that keeps the password here, "
                          "local). The others are registered beforehand and linked on the first sign-in."))
    p.add_argument("--role", help=_("Role of the user: admin, user or the key of a role (default: the one of new accounts)"))
    p.add_argument("--password", help=_("Password (avoid it: it stays in the shell history; better let it ask)"))
    p.add_argument("--password-stdin", action="store_true", help=_("Read the password from standard input"))
    p.add_argument("--name", help=_("Display name"))
    p.add_argument("--email", help=_("Email address"))
    p.add_argument("--groups", help=_("Comma-separated groups (they give access to shared folders)"))
    p.add_argument("--home", help=_("Custom personal folder (default storage.home_template)"))


@command("user-add", _l("Create a user (local by default)"), _user_add_args, order=30)
def cmd_user_add(cfg, conn, args):
    from ..core.accounts import AccountError, create_account, default_source, stores_password

    source = args.source or default_source()
    password = None
    if stores_password(source):
        password = _read_password(args) or _prompt_password()
    from ..core.permissions import default_role
    role = args.role or default_role(effective(cfg, conn, args))
    try:
        create_account(conn, username=args.username, source=source, role=role,
                       password=password, display_name=args.name, email=args.email,
                       groups=_groups(args.groups), home_path=args.home,
                       password_rules=password_rules(cfg, conn, args), cfg=effective(cfg, conn, args))
    except AccountError as exc:
        _fail(exc.message)
    audit.log(conn, "user_created", args.username, username="cli", detail=f"{source}:{role}")
    print(_("User %(name)s (%(source)s, %(role)s) created.", name=repr(args.username), source=source, role=role))


def _user_passwd_args(p):
    p.add_argument("username", help=_("User name"))
    p.add_argument("--password", help=_("New password (asked if omitted)"))
    p.add_argument("--password-stdin", action="store_true", help=_("Read the password from standard input"))


@command("user-passwd", _l("Change the password of a local user"), _user_passwd_args, order=31)
def cmd_user_passwd(cfg, conn, args):
    from ..core.accounts import AccountError, set_password
    user = _get(conn, args.username)
    if not stores_password(user["source"]):
        _fail(_("%(name)s is a %(source)s user; its password is not managed here.",
                name=repr(args.username), source=user["source"]))
    try:
        closed = set_password(conn, user, None, _read_password(args) or _prompt_password(),
                              password_rules=password_rules(cfg, conn, args))     # cierra sus sesiones
    except AccountError as exc:
        _fail(exc.message)
    audit.log(conn, "password_reset_by_admin", user["username"], username="cli", detail=f"sessions_closed={closed}")
    print(_("Password updated."))


def _user_set_args(p):
    p.add_argument("username", help=_("User name"))
    p.add_argument("--role", help=_("New role: admin, user or the key of a role"))
    p.add_argument("--groups", help=_("Comma-separated groups (replace the current ones)"))
    p.add_argument("--home", help=_("Personal folder; '' to go back to storage.home_template"))
    p.add_argument("--name", help=_("Display name"))
    p.add_argument("--email", help=_("Email address"))
    p.add_argument("--locale", choices=i18n.LOCALES, help=_("Preferred interface language"))
    g = p.add_mutually_exclusive_group()
    g.add_argument("--enable", action="store_true", help=_("Enable the account"))
    g.add_argument("--disable", action="store_true", help=_("Disable the account"))


def _username_arg(p):
    p.add_argument("username", help=_("User name"))


@command("user-set", _l("Change the role, groups, folder, language or status of a user"), _user_set_args, order=32)
def cmd_user_set(cfg, conn, args):
    from ..core.accounts import AccountError, check_home_path, set_enabled, set_role
    user = _get(conn, args.username)
    fields = {}
    if args.home is not None:
        try:
            check_home_path(effective(cfg, conn, args), args.home)
        except AccountError as exc:
            _fail(exc.message)
        fields["home_path"] = args.home
    if args.name is not None:
        fields["display_name"] = args.name
    if args.email is not None:
        fields["email"] = args.email
    if args.locale is not None:
        fields["locale"] = i18n.normalize(args.locale)
    enabled = True if args.enable else False if args.disable else None
    if not fields and args.groups is None and args.role is None and enabled is None:
        _fail(_("Nothing to change."))
    try:
        if args.role is not None:
            set_role(conn, user, None, args.role)
        if enabled is not None:
            set_enabled(conn, user, None, enabled)     # al desactivar, fuera sus sesiones
    except AccountError as exc:
        _fail(exc.message)
    if fields:
        users.update(conn, user["id"], **fields)
    if args.role is not None:
        fields["role"] = args.role
    if enabled is not None:
        fields["enabled"] = enabled
        audit.log(conn, "user_enabled" if enabled else "user_disabled", user["username"], username="cli",
                  detail=user["source"])
    if args.groups is not None:
        from ..core import groups as group_core

        group_core.set_manual_groups(conn, user["id"], _groups(args.groups))
        fields["groups"] = True
    audit.log(conn, "user_updated", user["username"], username="cli", detail=",".join(fields))
    print(_("User %(name)s updated: %(fields)s", name=repr(args.username), fields=", ".join(fields)))


@command("user-del", _l("Delete a user (their files are not removed)"), _username_arg, order=33)
def cmd_user_del(cfg, conn, args):
    from ..core.accounts import delete_account
    user = _get(conn, args.username)
    delete_account(conn, user, None)
    audit.log(conn, "user_deleted", user["username"], username="cli")
    print(_("User %(name)s deleted (their files have NOT been removed).", name=repr(args.username)))


@command("user-exists", _l("Exit code 0 if the user exists, 1 if not"), _username_arg, order=35)
def cmd_user_exists(cfg, conn, args):
    sys.exit(0 if users.get_by_username(conn, args.username) else 1)


@command("user-list", _l("List users"), order=34)
def cmd_user_list(cfg, conn, args):
    fmt = "{:<32} {:<6} {:<6} {:<4} {:<25} {:<20} {}"
    print(fmt.format(_("USER"), _("SOURCE"), _("ROLE"), _("ON"), _("GROUPS"), _("LAST SIGN-IN"), _("HOME")))
    for r in users.list_all(conn):
        print(fmt.format(r["username"], r["source"], r["role"], _("yes") if r["enabled"] else _("no"),
                         (r["groups"] or "")[:25], (r["last_login"] or "-")[:19],
                         r["home_path"] or _("(template)")))

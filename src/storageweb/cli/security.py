"""Comandos de rescate: IPs bloqueadas y sesiones."""
from __future__ import annotations


from ..db.repositories import audit
from ..i18n import _, _l, ngettext
from .common import _fail, _get, command


@command("ip-list", _l("List blocked and allowed IP addresses"), order=130)
def cmd_ip_list(cfg, conn, args):
    from ..db.repositories import ip_rules

    rows = ip_rules.list_rules(conn)
    if not rows:
        print(_("There are no blocked or allowed addresses."))
    for r in rows:
        until = r["expires_at"] or _("indefinitely")
        kind = _("blocked") if r["kind"] == "ban" else _("allowed")
        print(f"{r['id']:>4}  {kind:<10} {r['network']:<40} {until:<26} {r['reason']}")


def _ip_unban_args(p):
    p.add_argument("network", nargs="?", help=_("IP address or network (CIDR)"))
    p.add_argument("--all", action="store_true", help=_("Remove every block"))


@command("ip-unban", _l("Unblock an IP address or network (rescue if you blocked yourself)"), _ip_unban_args,
         order=131)
def cmd_ip_unban(cfg, conn, args):
    from ..core import ipban
    from ..db.repositories import ip_rules

    if args.all:
        removed = ip_rules.delete_all(conn, "ban")
        ip_rules.clear_offenses(conn, before_iso="9999")
    else:
        try:
            network = ipban.normalize_network(args.network or "")
        except ipban.IPBanError as exc:
            _fail(str(exc))
        removed = ip_rules.delete_network(conn, "ban", network)
        ip_rules.clear_offenses(conn, ip=network)
    audit.log(conn, "ip_unbanned", args.network or "*", username="cli", detail=str(removed))
    print(_("%(num)s block(s) removed (the service notices within 30 seconds).", num=removed))


def _ip_allow_args(p):
    p.add_argument("network", help=_("IP address or network (CIDR)"))
    p.add_argument("--reason", help=_("Note"))


@command("ip-allow", _l("Add an IP address or network to the allow list (never blocked)"), _ip_allow_args,
         order=132)
def cmd_ip_allow(cfg, conn, args):
    from ..core import ipban

    try:
        network = ipban.allow(conn, args.network, by="cli", reason=args.reason or "")
    except ipban.IPBanError as exc:
        _fail(str(exc))
    audit.log(conn, "ip_allowed", network, username="cli")
    print(_("%(network)s added to the allow list.", network=network))


def _sessions_close_args(p):
    p.add_argument("username", nargs="?", help=_("User name"))
    p.add_argument("--all", action="store_true", help=_("Close every session"))


@command("sessions-close", _l("Close the open sessions of a user (or of everybody)"), _sessions_close_args,
         order=133)
def cmd_sessions_close(cfg, conn, args):
    from ..db.repositories import sessions

    if args.all:
        closed = sessions.delete_all(conn)
    else:
        closed = sessions.delete_for_user(conn, _get(conn, args.username)["id"])
    audit.log(conn, "sessions_closed", args.username or "*", username="cli", detail=str(closed))
    print(_("%(num)s session(s) closed.", num=closed))


def _mfa_reset_args(p):
    p.add_argument("username")


@command("mfa-reset", _l("Remove the two-step verification of a user (lost phone and recovery codes)"),
         _mfa_reset_args, order=134)
def cmd_mfa_reset(cfg, conn, args):
    from ..core import mfa

    user = _get(conn, args.username)
    if not mfa.disable(conn, user):
        print(_("«%(name)s» does not have two-step verification.", name=user["username"]))
        return 0
    audit.log(conn, "mfa_reset_by_admin", user["username"], username="cli")
    print(_("Two-step verification removed from «%(name)s».", name=user["username"]))
    return 0


@command("mfa-status", _l("List which accounts have two-step verification"), order=135)
def cmd_mfa_status(cfg, conn, args):
    from ..core import mfa
    from ..db.repositories import users

    for user in users.list_all(conn):
        if not mfa.applies(user):
            continue
        state = mfa.status(conn, user)
        if state["enrolled"]:
            how = ([_("app")] if state["totp"] else []) + (
                [ngettext("%(num)s passkey", "%(num)s passkeys", len(state["passkeys"]))] if state["passkeys"] else [])
            text = _("on: %(how)s (%(num)s recovery codes left)", how=", ".join(how), num=state["recovery_left"])
        else:
            text = _("required, not set up") if mfa.required(cfg, user) else _("off")
        print(f"{user['username']:<32} {text}")
    return 0


def _password_list_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--download", action="store_true",
                   help=_("Download it from security.password_list_urls (or --url) as the own list"))
    g.add_argument("--file", help=_("Use this text file (one password per line) as the own list"))
    g.add_argument("--reset", action="store_true", help=_("Delete the own list: the built-in one is used again"))
    p.add_argument("--url", action="append", help=_("Address to download from (instead of the setting); repeatable"))


@command("password-list", _l("Show, download or replace the list of common passwords"), _password_list_args,
         order=136)
def cmd_password_list(cfg, conn, args):
    from ..core import passwords
    from .common import effective

    data_dir = cfg["data_dir"]
    try:
        if args.download:
            urls = args.url or effective(cfg, conn, args)["security"]["password_list_urls"]
            count = passwords.download(data_dir, urls)
            audit.log(conn, "password_list_updated", None, username="cli", detail="download")
            print(_("Common passwords list updated: %(num)s passwords.", num=count))
        elif args.file:
            with open(args.file, "rb") as fh:
                count = passwords.upload(data_dir, fh.read(passwords.MAX_BYTES + 1), args.file)
            audit.log(conn, "password_list_updated", None, username="cli", detail="upload")
            print(_("Common passwords list updated: %(num)s passwords.", num=count))
        elif args.reset:
            if passwords.reset(data_dir):
                audit.log(conn, "password_list_reset", None, username="cli")
            print(_("The list that comes with StorageWeb is used again."))
    except passwords.PasswordListError as exc:
        _fail(exc.message)
    except OSError as exc:
        _fail(str(exc))
    state = passwords.status(data_dir)
    if state["own"]:
        print(_("Own list of this server: %(num)s passwords, from %(source)s, updated %(when)s.", num=state["count"],
                source=state["source"], when=state["updated_at"]))
    else:
        print(_("The list that comes with StorageWeb: %(num)s passwords (SecLists).", num=state["count"]))
    return 0

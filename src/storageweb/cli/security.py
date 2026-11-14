"""Comandos de rescate: IPs bloqueadas y sesiones."""
from __future__ import annotations


from ..db.repositories import audit
from ..i18n import _, _l
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
        closed = conn.execute("DELETE FROM sessions").rowcount
        conn.commit()
    else:
        closed = sessions.delete_for_user(conn, _get(conn, args.username)["id"])
    audit.log(conn, "sessions_closed", args.username or "*", username="cli", detail=str(closed))
    print(_("%(num)s session(s) closed.", num=closed))

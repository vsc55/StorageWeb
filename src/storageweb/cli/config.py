"""Comandos de base de datos, configuración y auditoría."""
from __future__ import annotations

from pathlib import Path

from ..db.repositories import audit, users
from ..i18n import _


def cmd_init_db(cfg, conn, args):
    print(_("Database ready: %(path)s", path=cfg["database"]))


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
        (_("Public URL"), cfg["network"]["public_url"] or _("(host of each request)")),
        (_("Proxy"), _("yes, %(hops)s hop(s)", hops=cfg["server"]["proxy_hops"]) if cfg["server"]["behind_proxy"]
         else _("no")),
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
    from ..db.repositories import settings as settings_repo
    from ..settings import runtime_key

    settings_repo.put(conn, runtime_key(cfg["settings_profile"]), {}, "cli")
    audit.log(conn, "settings_reset", username="cli", detail=cfg["settings_profile"])
    print(_("Web settings of the profile %(profile)s discarded: the default values apply again, except what "
            "config.json and the environment set (the service notices on the next request).",
            profile=cfg["settings_profile"]))

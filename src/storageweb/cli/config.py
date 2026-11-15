"""Comandos de base de datos, configuración y auditoría."""
from __future__ import annotations

from .. import providers
from ..core import locations
from ..db.repositories import audit, users
from ..i18n import _, _l
from .common import command


@command("init-db", _l("Create the database or apply pending migrations"), order=20)
def cmd_init_db(cfg, conn, args):
    print(_("Database ready: %(path)s", path=cfg["database"]))


def _audit_args(p):
    p.add_argument("--limit", type=int, default=50, help=_("Maximum number of entries"))
    p.add_argument("--user", help=_("Filter by user"))


@command("audit", _l("Show the audit log"), _audit_args, order=100)
def cmd_audit(cfg, conn, args):
    for r in audit.recent(conn, args.limit, username=args.user):
        print(f"{r['ts']}  {r['username'] or '-':<25} {r['action']:<16} {r['target'] or '':<40} "
              f"{r['ip'] or ''} {r['detail'] or ''}")


@command("check-config", _l("Validate the configuration and warn if there is no administrator"), order=110)
def cmd_check_config(cfg, conn, args):
    rows = [
        (_("Config"), cfg["_config_path"]),
        (_("Database"), cfg["database"]),
        (_("Homes"), locations.where(cfg, cfg["storage"]["home_location"], cfg["storage"]["home_template"])),
        (_("Language"), cfg["default_locale"]),
        (_("Public URL"), cfg["network"]["public_url"] or _("(host of each request)")),
        (_("Proxy"), _("yes, %(hops)s hop(s)", hops=cfg["server"]["proxy_hops"]) if cfg["server"]["behind_proxy"]
         else _("no")),
        (_("Sign-in"), " ".join(f"{m.key}={m.enabled(cfg)}" for m in providers.methods())),
    ]
    for loc in cfg["storage"]["locations"]:
        rows.append((_("Location"), f"{loc['name']:<15} {locations.describe(loc)}"))
    for s in cfg["storage"]["shares"]:
        exists = locations.local_exists(s["location"], s["path"])
        state = _("remote") if exists is None else _("OK") if exists else _("MISSING")
        rows.append((_("Share"), f"{s['name']:<15} {locations.where(cfg, s['location'], s['path'])} [{state}] "
                                 f"ro={s['read_only']} "
                                 f"users={s['users']} groups={s['groups']}"))
    width = max(len(label) for label, _value in rows) + 2
    for label, value in rows:
        print(f"{label + ':':<{width}}{value}")
    if users.count_admins(conn) == 0:
        print(_("WARNING: there is no administrator. Create one with: user-add <user> --role admin"))
    print(_("Valid configuration."))


@command("settings-reset", _l("Discard the settings saved from the web and go back to the default values"), order=120)
def cmd_settings_reset(cfg, conn, args):
    """Vía de rescate si unos ajustes web dejan a todos sin poder entrar."""
    from ..settings import store

    store.put_doc(conn, cfg["settings_profile"], {}, "cli")
    audit.log(conn, "settings_reset", username="cli", detail=cfg["settings_profile"])
    print(_("Web settings of the profile %(profile)s discarded: the default values apply again, except what "
            "config.json and the environment set (the service notices on the next request).",
            profile=cfg["settings_profile"]))

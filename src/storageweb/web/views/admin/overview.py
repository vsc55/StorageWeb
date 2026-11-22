"""Resumen de la administración y buscador (Ctrl+K)."""
from __future__ import annotations


from flask import jsonify, render_template, request

from .... import providers
from ....core import locations as location_core
from ....core import maintenance
from ....core import shares as share_core
from ....core.permissions import PERMISSION_LABELS
from ....db.repositories import api_tokens, audit, users
from ....db.repositories import groups as group_repo
from ....db.repositories import ip_rules as ip_repo
from ....db.repositories import sessions as session_repo
from ....settings import PERMISSIONS
from ... import nav
from ... import search as admin_search
from ...context import admin_alerts, boot_config, get_db, settings
from ...guards import admin_required
from . import bp
from ....clock import iso_ago


# --------------------------------------------------------------------------- Resumen y buscador


@bp.route("/")
@admin_required
def index():
    conn, cfg = get_db(), settings()
    found = admin_alerts()
    sessions = session_repo.list_all(conn)
    bans = ip_repo.list_rules(conn, "ban")
    backups = maintenance.list_backups(boot_config())
    day_ago = iso_ago(days=1)
    shares = [{"share": s, "exists": location_core.local_exists(s["location"], s["path"]) is not False
                         or cfg["storage"]["create_shares"],
               "entries": share_core.entries(s)} for s in cfg["storage"]["shares"]]
    methods = [str(m.label) for m in providers.methods() if m.enabled(cfg)]
    return render_template(
        "admin/overview.html", alerts=found, user_counts=users.counts(conn), groups=len(group_repo.list_all(conn)),
        online=len({r["user_id"] for r in sessions}), tokens=len(api_tokens.list_all(conn)), shares=shares,
        role_perms=[PERMISSION_LABELS[p] for p in PERMISSIONS if cfg["permissions"]["user"][p]],
        methods=methods, failed_logins=audit.count_since(conn, "login_failed", day_ago),
        bans=len(bans), auto_bans=sum(1 for b in bans if b["automatic"]),
        public_url=cfg["network"]["public_url"], newest_backup=backups[0] if backups else None,
        backup_count=len(backups), db_size=maintenance.db_stats(conn, boot_config()["database"])["size"],
        recent=audit.recent(conn, 6), z={zone.key: zone for zone in nav.ZONES})


@bp.route("/search")
@admin_required
def search():
    """Buscador de la administración: JSON para el diálogo (Ctrl+K) o una página de resultados sin JavaScript."""
    query = request.args.get("q", "").strip()
    results = admin_search.find(query, get_db(), settings())
    if request.args.get("format") == "json":
        return jsonify(query=query, results=results)
    return render_template("admin/search.html", query=query, results=results)

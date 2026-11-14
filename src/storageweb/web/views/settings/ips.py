"""IPs bloqueadas y lista blanca (Seguridad → IPs bloqueadas)."""
from __future__ import annotations

from flask import abort, flash, g, redirect, request, url_for

from ....core import ipban
from ....i18n import _, _l
from ...context import get_db
from ...guards import admin_required, audit_event, client_ip
from ... import search
from . import bp


# --------------------------------------------------------------------------- IPs bloqueadas y permitidas

@bp.route("/security/ip", methods=["POST"])
@admin_required
def ip_add():
    kind = request.form.get("kind")
    network, reason = request.form.get("network", ""), request.form.get("reason", "")
    try:
        if kind == "ban":
            net = ipban.ban(get_db(), network, by=g.user["username"], reason=reason,
                            minutes=request.form.get("minutes", 0, type=int) or 0, current_ip=client_ip())
            audit_event("ip_banned", net, f"manual:{reason}"[:200])
            flash(_("%(network)s blocked.", network=net), "info")
        elif kind == "allow":
            net = ipban.allow(get_db(), network, by=g.user["username"], reason=reason)
            audit_event("ip_allowed", net, reason[:200] or None)
            flash(_("%(network)s added to the allow list.", network=net), "info")
        else:
            abort(400)
    except ipban.IPBanError as exc:
        flash(str(exc), "error")
    return redirect(url_for("settings.section", name="ips"))


@bp.route("/security/ip/<int:rule_id>/delete", methods=["POST"])
@admin_required
def ip_remove(rule_id: int):
    rule = ipban.remove(get_db(), rule_id)
    if rule:
        audit_event("ip_unbanned" if rule["kind"] == "ban" else "ip_allow_removed", rule["network"])
        flash(_("%(network)s removed.", network=rule["network"]), "info")
    return redirect(url_for("settings.section", name="ips"))


search.action("lock", _l("Block an IP address"), "settings.section", {"name": "ips"}, "ip-rules", "ip bloquear ban",
              order=50)

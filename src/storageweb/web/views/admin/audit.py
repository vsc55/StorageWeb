"""Auditoría: consulta y exportación CSV."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from flask import Response, render_template, request

from ....db.repositories import audit
from ...context import get_db
from ...guards import admin_required, audit_event
from . import bp


# --------------------------------------------------------------------------- auditoría

@bp.route("/audit")
@admin_required
def audit_log():
    username = request.args.get("user", "").strip() or None
    action = request.args.get("action", "").strip() or None
    rows = audit.recent(get_db(), limit=500, username=username, action=action)
    return render_template("admin/audit.html", rows=rows, user_filter=username or "",
                           action_filter=action or "")


@bp.route("/audit/export.csv")
@admin_required
def audit_export():
    """Toda la auditoría (o la filtrada) en CSV, con BOM para que Excel respete los acentos."""
    username = request.args.get("user", "").strip() or None
    action = request.args.get("action", "").strip() or None
    rows = audit.recent(get_db(), limit=1_000_000, username=username, action=action)
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out)
    writer.writerow(["ts", "username", "action", "target", "ip", "detail"])
    for r in rows:
        writer.writerow([r["ts"], r["username"] or "", r["action"], r["target"] or "", r["ip"] or "", r["detail"] or ""])
    audit_event("audit_exported", None, f"{len(rows)} rows")
    name = f"storageweb-audit-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return Response(out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})

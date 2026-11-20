"""Auditoría: consulta y exportación CSV."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from flask import Response, render_template, request

from .... import audit_levels
from ....db.repositories import audit
from ....i18n import _l
from ...context import get_db
from ...guards import admin_required, audit_event
from ... import search
from . import bp


# --------------------------------------------------------------------------- auditoría

PAGE_SIZES = (25, 50, 100, 250, 500)
PAGE_SIZE = 100  # por defecto

@bp.route("/audit")
@admin_required
def audit_log():
    username = request.args.get("user", "").strip() or None
    action = request.args.get("action", "").strip() or None
    level = _level_filter()
    size = request.args.get("per_page", PAGE_SIZE, type=int)
    size = size if size in PAGE_SIZES else PAGE_SIZE
    total = audit.count(get_db(), username=username, action=action, min_level=level)
    pages = max((total + size - 1) // size, 1)
    page = min(max(request.args.get("page", 1, type=int), 1), pages)
    rows = audit.recent(get_db(), limit=size, offset=(page - 1) * size, username=username, action=action,
                        min_level=level)
    return render_template("admin/audit.html", rows=rows, user_filter=username or "", action_filter=action or "",
                           level_filter=level or "", total=total, page=page, pages=pages, page_size=size,
                           PAGE_SIZES=PAGE_SIZES)


def _level_filter() -> str | None:
    """``?level=``: de ese nivel hacia arriba (``debug`` o nada = todos)."""
    level = request.args.get("level", "").strip()
    return level if level in audit_levels.RANK and level != "debug" else None


@bp.route("/audit/export.csv")
@admin_required
def audit_export():
    """Toda la auditoría (o la filtrada) en CSV, con BOM para que Excel respete los acentos."""
    username = request.args.get("user", "").strip() or None
    action = request.args.get("action", "").strip() or None
    rows = audit.recent(get_db(), limit=1_000_000, username=username, action=action, min_level=_level_filter())
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out)
    writer.writerow(["ts", "level", "username", "action", "target", "ip", "detail"])
    for r in rows:
        writer.writerow([r["ts"], r["level"], r["username"] or "", r["action"], r["target"] or "", r["ip"] or "", r["detail"] or ""])
    audit_event("audit_exported", None, f"{len(rows)} rows")
    name = f"storageweb-audit-{datetime.now(timezone.utc):%Y%m%d-%H%M}.csv"
    return Response(out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


search.action("audit", _l("Export the audit log (CSV)"), "admin.audit_export", words="auditoría exportar csv",
              order=90)

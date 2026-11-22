"""*Seguridad → Estado de la seguridad* (el tablero: cifras de un vistazo, la lista de comprobación de
``core/posture.py`` y los últimos sucesos de seguridad) y *Seguridad → Vulnerabilidades* (``core/advisories.py``:
el último resultado; el botón, su barra de progreso y la comprobación en marcha están en ``system.py``)."""
from __future__ import annotations


from ....core import advisories, maintenance, posture
from ....db.repositories import api_tokens, audit, ip_rules, sessions
from ... import nav
from ...context import boot_config, get_db, network_diagnosis, runtime
from ....clock import iso_ago, now_iso

EVENTS_SHOWN = 12


def _active_bans(conn) -> tuple[int, int]:
    """IPs bloqueadas ahora mismo: ``(total, automáticas)`` (las caducadas no cuentan)."""
    now = now_iso()
    rows = [r for r in ip_rules.list_rules(conn, "ban") if not r["expires_at"] or r["expires_at"] > now]
    return len(rows), sum(1 for r in rows if r["automatic"])


def security_context(cfg: dict) -> dict:
    conn = get_db()
    state = maintenance.state(conn)
    now, day_ago = now_iso(), iso_ago(hours=24)
    checks = posture.collect(posture.Context(conn, cfg, boot_config(), state, network_diagnosis(cfg),
                                             runtime().secrets_key is not None))
    for row in checks:
        row["url"] = nav.PAGES[row["page"]].url() + (f"#{row['anchor']}" if row["anchor"] else "")
    bans, automatic = _active_bans(conn)
    open_sessions = sessions.list_all(conn)
    valid_tokens = [t for t in api_tokens.list_all(conn)
                    if not t["expires_at"] or t["expires_at"] > now]
    accounts = posture.password_accounts(conn)
    enrolled = posture.enrolled_ids(conn)
    last = state.get(advisories.STATE_KEY) or {}
    tiles = {
        "vulns": {"value": last.get("vuln_total") if last.get("vulns_ok") else None, "worst": last.get("worst", ""),
                  "at": last.get("at", ""), "packages": last.get("vuln_packages", 0)},
        "bans": {"value": bans, "automatic": automatic},
        "failed": {"value": audit.count_since(conn, "login_failed", day_ago) + audit.count_since(conn, "mfa_failed",
                                                                                                  day_ago),
                   "blocked": audit.count_since(conn, "login_blocked", day_ago)},
        "sessions": {"value": len(open_sessions), "admins": sum(1 for s in open_sessions if s["role"] == "admin")},
        "mfa": {"value": sum(1 for u in accounts if u["id"] in enrolled), "total": len(accounts)},
        "tokens": {"value": len(valid_tokens)},
    }
    return {"posture": checks, "posture_summary": posture.summary(checks), "tiles": tiles,
            "events": audit.recent(conn, EVENTS_SHOWN, min_level="warning")}


def vulnerabilities_context() -> dict:
    """*Seguridad → Vulnerabilidades*: el último resultado y la comprobación en marcha (el botón y su barra)."""
    return {"advisories": maintenance.state(get_db()).get(advisories.STATE_KEY),
            "advisories_job": advisories.job_status()}

"""Monitorización: lo que se calcula al leer ``/metrics`` y la tarea que lo mantiene al día.

Al leer (``snapshot``) solo se consulta la base de datos y lo que ya está en memoria: nunca se recorre una
carpeta ni se conecta a una ubicación remota, porque Prometheus lee cada pocos segundos y espera una respuesta
rápida. Eso lo hace la tarea de mantenimiento ``monitoring`` (cada 10 minutos mientras las métricas estén
activas): calcula lo que ocupa cada carpeta compartida (la caché de ``quota``) y prueba cada ubicación remota.
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import threading
import time
from datetime import datetime
from sqlite3 import Connection

from .. import __version__, metrics
from ..db.connection import db_size, now_iso
from . import alerts, locations, maintenance, quota, storage

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_locations: dict[str, dict] = {}   # nombre → {"type", "up", "at", "error"}


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("metrics", {}).get("enabled"))


# --------------------------------------------------------------------------- acceso a /metrics

def allowed(cfg: dict, ip: str, bearer: str | None) -> bool:
    """Si se pueden leer las métricas: con el token, desde una red permitida o, si no hay ninguno de los dos
    configurado, solo desde el propio servidor."""
    settings = cfg["metrics"]
    if settings["token"] and bearer and hmac.compare_digest(bearer.encode(), settings["token"].encode()):
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if settings["allowed_networks"]:
        return any(addr in ipaddress.ip_network(net) for net in settings["allowed_networks"])
    return not settings["token"] and addr.is_loopback


# --------------------------------------------------------------------------- tarea periódica

def share_roots(cfg: dict) -> list[dict]:
    return [storage.make_root(cfg, s["name"], s["label"], s.get("location", ""), s["path"],
                              quota_mb=s.get("quota_mb", 0)) for s in cfg["storage"]["shares"]]


def refresh(cfg: dict) -> None:
    """Lo caro, fuera de la lectura: el uso de cada carpeta compartida y el estado de cada ubicación remota."""
    for root in share_roots(cfg):
        try:
            quota.usage(root)
        except Exception:  # noqa: BLE001 (una carpeta que falla no para las demás)
            _log.exception("Usage of %s could not be measured", root["name"])
    found = {}
    for loc in cfg["storage"].get("locations", []):
        error = locations.test(cfg, loc)
        found[loc["name"]] = {"type": loc.get("type", ""), "up": error is None, "at": time.time(), "error": error}
    with _lock:
        _locations.clear()
        _locations.update(found)


@maintenance.task("monitoring", every=lambda cfg: 1 / 6 if enabled(cfg) else 0, order=60)
def _refresh(conn: Connection, cfg: dict) -> None:
    refresh(cfg)


# --------------------------------------------------------------------------- lectura

def _ts(iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


def snapshot(conn: Connection, cfg: dict, boot: dict) -> list[metrics.Family]:
    """Las métricas calculadas al leer (sin recorrer carpetas ni conectar a nada)."""
    F = metrics.Family
    out = [F("storageweb_info", "gauge", "StorageWeb version.", [({"version": __version__}, 1)]),
           F("storageweb_start_time_seconds", "gauge", "When this process started (Unix time).",
             [({}, metrics.START_TIME)])]

    users = F("storageweb_users", "gauge", "Accounts by source and state.")
    for row in conn.execute("SELECT source, enabled, COUNT(*) FROM users GROUP BY source, enabled"):
        users.samples.append(({"source": row[0], "state": "enabled" if row[1] else "disabled"}, row[2]))
    out.append(users)
    out.append(F("storageweb_sessions", "gauge", "Open web sessions.",
                 [({}, conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])]))
    out.append(F("storageweb_api_tokens", "gauge", "API tokens that have not expired.",
                 [({}, conn.execute("SELECT COUNT(*) FROM api_tokens WHERE expires_at IS NULL OR expires_at > ?",
                                    (now_iso(),)).fetchone()[0])]))
    out.append(F("storageweb_ip_bans", "gauge", "Blocked IP addresses or networks in force.",
                 [({}, conn.execute("SELECT COUNT(*) FROM ip_rules WHERE kind = 'ban' AND "
                                    "(expires_at IS NULL OR expires_at > ?)", (now_iso(),)).fetchone()[0])]))

    used = F("storageweb_folder_used_bytes", "gauge", "Space used by each shared folder (measured every 10 minutes).")
    limit = F("storageweb_folder_quota_bytes", "gauge", "Quota of each shared folder (0 = none).")
    free = F("storageweb_folder_free_bytes", "gauge", "Free space where each shared folder is stored, when known.")
    for root in share_roots(cfg):
        labels = {"folder": root["name"]}
        limit.samples.append((labels, quota.limit_bytes(root)))
        hit = quota.peek(root)
        if hit is not None:
            used.samples.append((labels, hit[0]))
        try:
            space = root["backend"].space("") or {}
        except Exception:  # noqa: BLE001
            space = {}
        if "free" in space:
            free.samples.append((labels, space["free"]))
    out += [used, limit, free]

    with _lock:
        known = dict(_locations)
    up = F("storageweb_location_up", "gauge", "Whether each remote storage location answered its last check.")
    checked = F("storageweb_location_last_check_timestamp_seconds", "gauge", "When each location was last checked.")
    for loc in cfg["storage"].get("locations", []):
        state = known.get(loc["name"])
        if state is not None:
            up.samples.append(({"location": loc["name"], "type": loc.get("type", "")}, 1 if state["up"] else 0))
            checked.samples.append(({"location": loc["name"]}, state["at"]))
    out += [up, checked]

    state = maintenance.state(conn)
    runs = F("storageweb_maintenance_last_run_timestamp_seconds", "gauge", "When each maintenance task last ran.")
    for task, iso in sorted(state.items()):
        when = _ts(iso)
        if when is not None:
            runs.samples.append(({"task": task}, when))
    out.append(runs)
    backups = maintenance.list_backups(boot)
    out.append(F("storageweb_backups", "gauge", "Backups kept in <data_dir>/backups.", [({}, len(backups))]))
    newest = _ts(backups[0]["created"]) if backups else None
    if newest is not None:
        out.append(F("storageweb_backup_last_timestamp_seconds", "gauge", "When the newest backup was made.",
                     [({}, newest)]))
    size = db_size(boot["database"])
    out.append(F("storageweb_database_size_bytes", "gauge", "Size of the SQLite database (with its WAL).",
                 [({}, size)]))

    try:
        current = alerts.collect(cfg, boot, state)
    except Exception:  # noqa: BLE001 (un aviso roto no deja sin métricas)
        _log.exception("Alerts could not be collected for the metrics")
        current = []
    levels = {level: 0 for level in alerts.LEVELS}
    for item in current:
        levels[item["level"]] = levels.get(item["level"], 0) + 1
    out.append(F("storageweb_alerts", "gauge", "Alerts shown in the admin Overview, by level.",
                 [({"level": level}, count) for level, count in levels.items()]))
    return out


def render(conn: Connection, cfg: dict, boot: dict) -> str:
    return metrics.render([*snapshot(conn, cfg, boot), *metrics.counters()])


def location_states() -> dict[str, dict]:
    with _lock:
        return dict(_locations)


def reset() -> None:
    with _lock:
        _locations.clear()


__all__ = ["allowed", "enabled", "refresh", "render", "snapshot", "location_states", "reset"]

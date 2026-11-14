"""Bloqueo de direcciones IP.

* **Automático**: cada infracción (contraseña errónea, CSRF no válido, token de API no válido) se
  anota; con ``security.ipban_threshold`` infracciones en ``ipban_window_minutes`` la IP queda
  bloqueada ``ipban_minutes`` (0 = hasta que un admin la desbloquee).
* **Manual**: un admin bloquea una IP o una red CIDR, con o sin caducidad.
* **Lista blanca**: las IPs o redes permitidas nunca se bloquean ni cuentan infracciones.

Las direcciones de loopback nunca se bloquean automáticamente: sin ``server.behind_proxy`` todas las
peticiones que pasan por un proxy local llegan como 127.0.0.1, y bloquearla dejaría fuera a todos.

Las reglas se cachean unos segundos por proceso; ``invalidate()`` fuerza la recarga.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from ..db.repositories import audit
from ..db.repositories import ip_rules as repo
from ..i18n import _
from .maintenance import task

CACHE_SECONDS = 30
OFFENSE_KINDS = ("login_failed", "csrf", "bad_token")

_cache: dict = {"at": 0.0, "rules": None}
_lock = threading.Lock()


class IPBanError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_network(text: str) -> str:
    """``192.168.1.7`` → ``192.168.1.7``; ``10.0.0.0/8`` → ``10.0.0.0/8``. Lanza IPBanError si no es válida."""
    try:
        net = ipaddress.ip_network((text or "").strip(), strict=False)
    except ValueError as exc:
        raise IPBanError(_("%(value)s is not a valid IP address or network.", value=repr(text))) from exc
    single = net.num_addresses == 1
    return str(net.network_address) if single else str(net)


def _ip(value: str):
    try:
        return ipaddress.ip_address((value or "").split("%")[0])
    except ValueError:
        return None


def invalidate() -> None:
    with _lock:
        _cache["rules"] = None


def _rules(conn: Connection) -> list[tuple[str, object, str | None, dict]]:
    with _lock:
        if _cache["rules"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["rules"]
    rules = []
    for row in repo.list_rules(conn):
        try:
            rules.append((row["kind"], ipaddress.ip_network(row["network"], strict=False), row["expires_at"],
                          dict(row)))
        except ValueError:
            continue
    with _lock:
        _cache.update(at=time.monotonic(), rules=rules)
    return rules


def _match(conn: Connection, ip: str, kind: str) -> dict | None:
    addr = _ip(ip)
    if addr is None:
        return None
    now = _now().isoformat(timespec="seconds")
    for rule_kind, net, expires_at, row in _rules(conn):
        if rule_kind == kind and addr.version == net.version and addr in net and (not expires_at or expires_at > now):
            return row
    return None


def is_allowed(conn: Connection, ip: str) -> bool:
    return _match(conn, ip, "allow") is not None


def banned(conn: Connection, ip: str) -> dict | None:
    """La regla que bloquea ``ip`` (None si no está bloqueada o está en la lista blanca)."""
    if is_allowed(conn, ip):
        return None
    return _match(conn, ip, "ban")


def offense(conn: Connection, cfg: dict, ip: str, kind: str) -> bool:
    """Anota una infracción. Devuelve True si con ella la IP queda bloqueada."""
    sec = cfg["security"]
    addr = _ip(ip)
    if not sec["ipban_enabled"] or addr is None or addr.is_loopback or is_allowed(conn, ip):
        return False
    repo.add_offense(conn, str(addr), kind)
    since = (_now() - timedelta(minutes=sec["ipban_window_minutes"])).isoformat(timespec="seconds")
    count = repo.count_offenses(conn, str(addr), since)
    if count < sec["ipban_threshold"]:
        return False
    minutes = sec["ipban_minutes"]
    expires = (_now() + timedelta(minutes=minutes)).isoformat(timespec="seconds") if minutes else None
    reason = _("%(count)s offenses in %(minutes)s minutes (last one: %(kind)s)", count=count,
               minutes=sec["ipban_window_minutes"], kind=kind)
    repo.add(conn, "ban", str(addr), reason=reason, automatic=True, expires_at=expires)
    repo.clear_offenses(conn, ip=str(addr))
    invalidate()
    audit.log(conn, "ip_banned", str(addr), ip=str(addr), detail=f"auto:{kind}:{count}")
    return True


def ban(conn: Connection, network: str, *, by: str, reason: str = "", minutes: int = 0,
        current_ip: str | None = None) -> str:
    net = normalize_network(network)
    addr = _ip(current_ip or "")
    if addr is not None and addr.version == ipaddress.ip_network(net, strict=False).version \
            and addr in ipaddress.ip_network(net, strict=False):
        raise IPBanError(_("You cannot block the address you are using (%(ip)s).", ip=current_ip))
    expires = (_now() + timedelta(minutes=minutes)).isoformat(timespec="seconds") if minutes else None
    repo.add(conn, "ban", net, reason=reason.strip(), created_by=by, expires_at=expires)
    invalidate()
    return net


def allow(conn: Connection, network: str, *, by: str, reason: str = "") -> str:
    net = normalize_network(network)
    repo.add(conn, "allow", net, reason=reason.strip(), created_by=by)
    invalidate()
    return net


def remove(conn: Connection, rule_id: int) -> dict | None:
    rule = repo.get(conn, rule_id)
    if rule is not None:
        repo.delete(conn, rule_id)
        if rule["kind"] == "ban":
            repo.clear_offenses(conn, ip=rule["network"])
        invalidate()
    return dict(rule) if rule else None


@task("ipban_prune", every=lambda cfg: 1, order=15)
def prune(conn: Connection, cfg: dict) -> None:
    """Quita los bloqueos caducados y las infracciones fuera de la ventana."""
    repo.delete_expired(conn)
    window = cfg["security"]["ipban_window_minutes"]
    repo.clear_offenses(conn, before_iso=(_now() - timedelta(minutes=window)).isoformat(timespec="seconds"))
    invalidate()

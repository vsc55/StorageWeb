"""Avisos para los administradores: lo que necesita atención (Resumen y globo de la barra lateral).

Cada aviso dice en qué página se resuelve (``page``, una clave de ``web/nav.py``) para que la web
pueda enlazarlo. ``level`` es ``danger``, ``warn`` o ``info``; los ``info`` no cuentan en el globo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..i18n import _, format_datetime, ngettext
from . import maintenance
from .network import warnings as network_warnings

SECRET_WARN_DAYS = 30


def _alert(level: str, key: str, title: str, detail: str, page: str, action: str, anchor: str = "") -> dict:
    return {"level": level, "key": key, "title": title, "detail": detail, "page": page, "action": action,
            "anchor": anchor}


def secret_days(entra: dict) -> int | None:
    """Días hasta que caduca el secreto de Entra ID (negativo si ya caducó), o ``None`` si no se sabe."""
    if not entra.get("secret_expires") or not entra.get("client_id"):
        return None
    return (datetime.fromisoformat(entra["secret_expires"]) - datetime.now(timezone.utc)).days


def collect(cfg: dict, boot: dict, maint_state: dict, locked: dict | None = None,
            network: dict | None = None) -> list[dict]:
    """Avisos actuales, del más grave al menos.

    ``cfg`` son los ajustes efectivos, ``boot`` los de arranque, ``maint_state`` lo que guarda
    :func:`maintenance.state` (cuándo se intentó cada tarea), ``locked`` los campos fijados fuera de la
    web (``RuntimeSettings.locked()``) y ``network`` el diagnóstico de la petición (``core.network``).
    """
    alerts: list[dict] = []
    entra = cfg["auth"]["entra"]
    days = secret_days(entra)
    if days is not None and days <= SECRET_WARN_DAYS:
        date = format_datetime(entra["secret_expires"])
        if days < 0:
            alerts.append(_alert("danger", "secret_expired", _("The Entra ID client secret has expired"),
                                 _("Since %(date)s nobody can sign in with Microsoft.", date=date),
                                 "auth", _("Renew the secret"), "f-auth-entra-secret_expires"))
        else:
            alerts.append(_alert("danger" if days <= 7 else "warn", "secret_expiring",
                                 ngettext("The Entra ID client secret expires in %(num)s day",
                                          "The Entra ID client secret expires in %(num)s days", days),
                                 _("On %(date)s; after that nobody can sign in with Microsoft.", date=date),
                                 "auth", _("Renew the secret"), "f-auth-entra-secret_expires"))

    if not cfg["storage"]["create_shares"]:
        for share in cfg["storage"]["shares"]:
            if not Path(share["path"]).exists():
                alerts.append(_alert("warn", "share_missing",
                                     _("The shared folder «%(label)s» does not exist on the server",
                                       label=share["label"]),
                                     share["path"], "folders", _("Review the folder"), f"share-{share['name']}"))

    hours = cfg["maintenance"]["backup_interval_hours"]
    if hours:
        backups = maintenance.list_backups(boot)
        newest = backups[0]["created"] if backups else None
        limit = datetime.now(timezone.utc) - timedelta(hours=hours * 2 + 1)
        tried = maint_state.get("backup")  # sin copias y sin intento aún: recién instalado, no es un aviso
        if (newest is None and tried) or (newest is not None and datetime.fromisoformat(newest) < limit):
            alerts.append(_alert("warn", "backup_stale", _("Automatic backups are not being made"),
                                 _("The newest backup is from %(date)s.", date=format_datetime(newest)) if newest
                                 else _("There is no backup yet."),
                                 "backups", _("See the backups")))
    for level, text in (network_warnings(network) if network else []):
        alerts.append(_alert(level, "network", text, "", "network", _("Review the network")))

    if locked:
        files = sum(1 for source in locked.values() if source == "file")
        envs = len(locked) - files
        parts = []
        if files:
            parts.append(ngettext("%(num)s in config.json", "%(num)s in config.json", files))
        if envs:
            parts.append(ngettext("%(num)s in environment variables", "%(num)s in environment variables", envs))
        alerts.append(_alert("info", "locked", ngettext("%(num)s setting is locked", "%(num)s settings are locked",
                                                        len(locked)),
                             " · ".join(parts), "system", _("See which ones"), "layers-title"))

    order = {"danger": 0, "warn": 1, "info": 2}
    return sorted(alerts, key=lambda a: order[a["level"]])


def count(alerts: list[dict]) -> int:
    return sum(1 for a in alerts if a["level"] != "info")

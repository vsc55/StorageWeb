"""Estado por petición de la capa web: conexión a la base de datos y ajustes efectivos.

Es el único punto donde Flask (``g``/``current_app``) se une a las capas inferiores, que reciben
la conexión y la configuración como argumentos.
"""
from __future__ import annotations

from sqlite3 import Connection

from flask import current_app, g

from ..core import alerts, maintenance
from ..core.security import LoginThrottle
from ..db import connect
from ..settings import RuntimeSettings


def get_db() -> Connection:
    if "db" not in g:
        g.db = connect(current_app.config["SW"]["database"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def boot_config() -> dict:
    """Configuración de arranque (solo config.json)."""
    return current_app.config["SW"]


def runtime() -> RuntimeSettings:
    return current_app.extensions["storageweb.runtime"]


def settings() -> dict:
    """Configuración efectiva (config.json + ajustes web), cacheada durante la petición."""
    cfg = g.get("sw_settings")
    if cfg is None:
        cfg = g.sw_settings = runtime().current(get_db())
    return cfg


def invalidate_settings() -> None:
    g.pop("sw_settings", None)


def throttle() -> LoginThrottle:
    return current_app.extensions["storageweb.throttle"]


def external_url(endpoint: str, **values) -> str:
    """URL absoluta para terceros (Entra ID, enlaces): usa ``network.public_url`` si está definida.

    Si la dirección pública incluye una ruta (``https://www.empresa.es/archivos``) y el proxy no
    envía ``X-Forwarded-Prefix``, la ruta se antepone aquí.
    """
    from urllib.parse import urlsplit

    from flask import request, url_for

    base = settings()["network"]["public_url"]
    if not base:
        return url_for(endpoint, _external=True, **values)
    parts = urlsplit(base)
    path = url_for(endpoint, **values)
    prefix = parts.path.rstrip("/")
    if prefix and (request.script_root.rstrip("/") == prefix or path.startswith(prefix + "/")):
        prefix = ""
    return f"{parts.scheme}://{parts.netloc}{prefix}{path}"


def admin_alerts() -> list[dict]:
    """Avisos para los administradores (una vez por petición: los usan la barra lateral y el Resumen)."""
    if "admin_alerts" not in g:
        g.admin_alerts = alerts.collect(settings(), boot_config(), maintenance.state(get_db()))
    return g.admin_alerts

"""Estado por petición de la capa web: conexión a la base de datos y ajustes efectivos.

Es el único punto donde Flask (``g``/``current_app``) se une a las capas inferiores, que reciben
la conexión y la configuración como argumentos.
"""
from __future__ import annotations

from sqlite3 import Connection

from flask import current_app, g, request

from ..core import alerts, maintenance, network
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


def network_diagnosis(cfg: dict | None = None) -> dict:
    """Diagnóstico de red de esta petición (``core.network.diagnose`` con lo que ve Flask)."""
    orig = request.environ.get("werkzeug.proxy_fix.orig", {})
    facts = {"scheme": request.scheme, "host": request.host, "prefix": request.script_root or "/",
             "client": request.remote_addr or "", "peer": orig.get("REMOTE_ADDR") or request.remote_addr or "",
             "base": request.host_url.rstrip("/") + request.script_root}
    headers = {h: request.headers.get(h, "") for h in network.FORWARDED_HEADERS}
    return network.diagnose(facts, headers, cfg or settings(), boot_config())


def admin_alerts() -> list[dict]:
    """Avisos para los administradores, con el enlace a la página donde se resuelven.

    Se calculan una vez por petición; los usan el Resumen, el número de la barra lateral y el banner.
    """
    if "admin_alerts" not in g:
        from . import nav  # noqa: PLC0415 (nav necesita el contexto de la aplicación ya creado)
        found = alerts.collect(settings(), boot_config(), maintenance.state(get_db()), runtime().locked(),
                               network_diagnosis())
        g.admin_alerts = [{**a, "url": nav.PAGES[a["page"]].url() + (f"#{a['anchor']}" if a["anchor"] else "")}
                          for a in found]
    return g.admin_alerts

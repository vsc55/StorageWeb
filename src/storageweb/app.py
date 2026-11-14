"""Punto de ensamblado de la aplicación Flask."""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from flask import Flask, current_app, g, render_template
from werkzeug.exceptions import HTTPException

from . import __version__, i18n
from .core import alerts, branding, maintenance
from .core.permissions import ROLE_LABELS, is_admin
from .core.security import LoginThrottle, PathError
from .core.storage import RootNotFound
from .db import connect, init_db
from .i18n import _, _l
from .settings import RuntimeSettings, ensure_secret_key, normalize, read_config_file
from .web import js_messages, register_blueprints
from .web.views.profile import THEME_ICONS, THEME_LABELS, THEMES, current_theme
from .web import nav
from .web.context import admin_alerts, close_db, get_db, runtime, settings
from .web.guards import (check_csrf, csrf_token, ip_gate, load_current_user, reset_request_locale,
                         select_locale, set_security_headers)

# Nombres de los errores HTTP más habituales (los de Werkzeug están en inglés)
ERROR_NAMES = {
    400: _l("Bad request"),
    401: _l("Not signed in"),
    403: _l("Forbidden"),
    404: _l("Not found"),
    405: _l("Method not allowed"),
    413: _l("Request too large"),
    500: _l("Internal server error"),
}
ERROR_DESCRIPTIONS = {
    404: _l("The requested page or file does not exist."),
    405: _l("This operation is not allowed here."),
    413: _l("The request exceeds the maximum size allowed by the server."),
    500: _l("Something went wrong on the server. Try again later."),
}


def ua_summary(user_agent: str | None) -> str:
    """«Chrome · Windows» a partir del User-Agent (para la lista de sesiones)."""
    ua = user_agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari"), ("curl/", "curl"),
                                           ("python", "Python")) if key in ua), "")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iOS"),
                                          ("iPad", "iOS"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if key in ua), "")
    return " · ".join(x for x in (browser, system) if x) or (ua[:40] or "—")


def _entra_secret_alert(user) -> dict | None:
    """Aviso para los admins si el secreto de Entra ID caduca en 30 días o menos."""
    if not is_admin(user):
        return None
    ecfg = settings()["auth"]["entra"]
    days = alerts.secret_days(ecfg)
    return {"days": days, "date": ecfg["secret_expires"]} if days is not None and days <= alerts.SECRET_WARN_DAYS else None


def _admin_nav(user) -> dict:
    """Zonas de la administración, página actual y avisos (solo para administradores)."""
    if not is_admin(user):
        return {"nav_zones": (), "nav_zone": None, "nav_page": None, "admin_alert_count": 0}
    found = [a for a in admin_alerts() if a["level"] != "info"]
    return {**nav.context(runtime().changed_paths(get_db())), "admin_alert_count": len(found),
            "nav_alert_pages": {a["page"] for a in found}}


def _brand() -> dict:
    cfg = settings()
    color, logo = cfg["branding"]["primary_color"], cfg["branding"]["logo"]
    version = f"{color}{logo}"
    if logo:
        path = branding.logo_path(cfg)
        version += str(int(path.stat().st_mtime)) if path else ""
    return {"color": color, "logo": bool(logo and branding.logo_path(cfg)), "version": version or "0"}


def _maintenance_tick() -> None:
    """Cada 10 minutos lanza las tareas de mantenimiento en un hilo (no en los tests)."""
    if current_app.testing:
        return
    state = current_app.extensions["storageweb.maintenance"]
    now = time.monotonic()
    with state["lock"]:
        if now < state["next"]:
            return
        state["next"] = now + 600
    runtime_settings = current_app.extensions["storageweb.runtime"]
    database = current_app.config["SW"]["database"]
    logger = current_app.logger

    def work():
        conn = connect(database)
        try:
            maintenance.run_due(conn, runtime_settings.current(conn))
        except Exception:  # noqa: BLE001 (un fallo de mantenimiento no debe afectar al servicio)
            logger.exception("Maintenance task failed")
        finally:
            conn.close()

    threading.Thread(target=work, name="storageweb-maintenance", daemon=True).start()


def create_app(config_path: str | None = None) -> Flask:
    file_cfg, cfg_path = read_config_file(config_path)
    cfg = normalize(file_cfg, cfg_path)  # solo config.json: arranque (servidor, BD, sesión)

    app = Flask(__name__, template_folder="web/templates", static_folder="web/static",
                static_url_path="/static")
    app.config["SW"] = cfg
    app.config.update(
        SECRET_KEY=ensure_secret_key(cfg),
        MAX_CONTENT_LENGTH=cfg["server"]["max_upload_mb"] * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg["session"]["lifetime_hours"]),
        SESSION_COOKIE_NAME="storageweb_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=bool(cfg["session"]["cookie_secure"]),
        # Lax es necesario para que la cookie llegue en la redirección de vuelta desde Entra ID
        SESSION_COOKIE_SAMESITE="Lax",
    )
    app.extensions["storageweb.runtime"] = RuntimeSettings(file_cfg, cfg_path)
    app.extensions["storageweb.maintenance"] = {"next": 0.0, "lock": threading.Lock()}
    app.extensions["storageweb.throttle"] = LoginThrottle(cfg["security"]["max_login_failures"],
                                                          cfg["security"]["lockout_minutes"] * 60)

    if cfg["server"]["behind_proxy"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        hops = cfg["server"]["proxy_hops"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_port=hops, x_prefix=hops)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    applied = init_db(cfg["database"])
    if applied:
        app.logger.info("Applied migrations: %s", ", ".join(f"{v:03d}" for v in applied))

    # --- i18n en plantillas: {{ _("Text") }}, {{ _("Hi %(name)s", name=x) }}, {{ ngettext(...) }}
    app.jinja_env.add_extension("jinja2.ext.i18n")
    app.jinja_env.install_gettext_callables(i18n.raw_gettext, i18n.raw_ngettext, newstyle=True)
    app.jinja_env.filters["datetime"] = i18n.format_datetime
    app.jinja_env.filters["filesize"] = i18n.format_size
    app.jinja_env.filters["ua_summary"] = ua_summary

    # El orden importa: primero el usuario y su idioma, para que hasta el error de CSRF salga traducido
    app.before_request(ip_gate)
    app.before_request(load_current_user)
    app.before_request(select_locale)
    app.before_request(check_csrf)
    app.before_request(_maintenance_tick)
    app.after_request(set_security_headers)
    app.teardown_request(reset_request_locale)
    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_globals():
        user = g.get("user")
        return {"csrf_token": csrf_token, "app_name": settings()["app_name"], "current_user": user,
                "is_admin": is_admin(user), "ROLE_LABELS": ROLE_LABELS, "app_version": __version__,
                "current_locale": i18n.get_locale(),
                "available_locales": [(code, i18n.locale_display_name(code)) for code in i18n.LOCALES],
                "current_theme": current_theme(),
                "available_themes": [(code, THEME_LABELS[code], THEME_ICONS[code]) for code in THEMES],
                "js_messages": js_messages.catalog,
                "entra_secret_alert": _entra_secret_alert(user),
                "brand": _brand(), **_admin_nav(user)}

    def render_error(code: int, name: str, description: str | None):
        return render_template("error.html", code=code, name=name, description=description), code

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        # Si la descripción es la genérica de Werkzeug (en inglés), se usa la traducida
        description = exc.description
        if description == type(exc).description:
            description = ERROR_DESCRIPTIONS.get(exc.code, description)
        return render_error(exc.code, ERROR_NAMES.get(exc.code, exc.name), description)

    @app.errorhandler(PathError)
    @app.errorhandler(RootNotFound)
    def handle_not_found(exc):
        message = str(exc) if isinstance(exc, RootNotFound) and str(exc) else _("The requested path does not exist.")
        return render_error(404, ERROR_NAMES[404], message)

    register_blueprints(app)
    return app

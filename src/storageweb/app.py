"""Punto de ensamblado de la aplicación Flask."""
from __future__ import annotations

import logging
from datetime import timedelta

from flask import Flask, g, render_template
from werkzeug.exceptions import HTTPException

from . import __version__
from .core.permissions import ROLE_LABELS, is_admin
from .core.security import LoginThrottle, PathError
from .core.storage import RootNotFound
from .db import init_db
from .settings import RuntimeSettings, ensure_secret_key, normalize, read_config_file
from .web import register_blueprints
from .web.context import close_db, settings
from .web.guards import check_csrf, csrf_token, load_current_user, set_security_headers


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
    app.extensions["storageweb.throttle"] = LoginThrottle(cfg["security"]["max_login_failures"],
                                                          cfg["security"]["lockout_minutes"] * 60)

    if cfg["server"]["behind_proxy"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    applied = init_db(cfg["database"])
    if applied:
        app.logger.info("Migraciones aplicadas: %s", ", ".join(f"{v:03d}" for v in applied))

    app.teardown_appcontext(close_db)
    app.before_request(check_csrf)
    app.before_request(load_current_user)
    app.after_request(set_security_headers)

    @app.context_processor
    def inject_globals():
        user = g.get("user")
        return {"csrf_token": csrf_token, "app_name": settings()["app_name"], "current_user": user,
                "is_admin": is_admin(user), "ROLE_LABELS": ROLE_LABELS, "app_version": __version__}

    def render_error(code: int, name: str, description: str | None):
        return render_template("error.html", code=code, name=name, description=description), code

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        return render_error(exc.code, exc.name, exc.description)

    @app.errorhandler(PathError)
    @app.errorhandler(RootNotFound)
    def handle_not_found(exc):
        message = str(exc) if isinstance(exc, RootNotFound) and str(exc) else "La ruta solicitada no existe."
        return render_error(404, "Not Found", message)

    register_blueprints(app)
    return app

"""StorageWeb: servidor web para subir y descargar archivos."""
from __future__ import annotations

import logging
from datetime import timedelta

from flask import Flask, g, render_template
from werkzeug.exceptions import HTTPException

from . import auth, db, files
from .config import ensure_secret_key, load_config
from .security import LoginThrottle, check_csrf, csrf_token, set_security_headers

__version__ = "1.0.0"


def create_app(config_path: str | None = None) -> Flask:
    cfg = load_config(config_path)

    app = Flask(__name__)
    app.config["SW"] = cfg
    app.config.update(
        SECRET_KEY=ensure_secret_key(cfg),
        MAX_CONTENT_LENGTH=int(cfg["server"]["max_upload_mb"]) * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=cfg["session"]["lifetime_hours"]),
        SESSION_COOKIE_NAME="storageweb_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=bool(cfg["session"]["cookie_secure"]),
        # Lax es necesario para que la cookie llegue en la redirección de vuelta desde Entra ID
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if cfg["server"]["behind_proxy"]:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init_db(cfg["database"])
    app.extensions["sw_throttle"] = LoginThrottle(
        cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60
    )

    app.teardown_appcontext(db.close_db)
    app.before_request(check_csrf)
    app.before_request(auth.load_current_user)
    app.after_request(set_security_headers)

    @app.context_processor
    def inject_globals():
        return {"csrf_token": csrf_token, "app_name": cfg["app_name"], "current_user": g.get("user")}

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        return render_template("error.html", code=exc.code, name=exc.name,
                               description=exc.description), exc.code

    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    return app

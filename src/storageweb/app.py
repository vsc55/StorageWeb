"""Punto de ensamblado de la aplicación Flask: configuración de arranque, ajustes por capas y capa web."""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

from flask import Flask

from .core.security import LoginThrottle
from .db import init_db
from .settings import RuntimeSettings, ensure_secret_key, env_config, fields, normalize, read_config_file
from .web import init_web


def create_app(config_path: str | None = None) -> Flask:
    file_cfg, cfg_path = read_config_file(config_path)
    env_cfg = env_config()
    cfg = normalize(file_cfg, cfg_path, env_cfg=env_cfg)  # sin ajustes web: arranque (servidor, BD, sesión)

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
    app.extensions["storageweb.runtime"] = RuntimeSettings(file_cfg, cfg_path, env_cfg, cfg["settings_profile"])
    app.extensions["storageweb.runtime"].labeler = fields.label
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

    init_web(app)
    return app

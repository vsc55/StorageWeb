"""Capa web (Flask).

* ``views/``: páginas HTML (auth, files, admin, groups, profile)
* ``api/``: API JSON (subidas por partes, /healthz)
* ``context``: conexión a BD y ajustes por petición
* ``guards``: sesión, CSRF, control de acceso y cabeceras de seguridad
* ``templates/`` y ``static/``: frontend
"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from .api import health, uploads
    from .views import admin, auth, files, groups, profile

    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(groups.bp)
    app.register_blueprint(profile.bp)
    app.register_blueprint(uploads.bp)
    app.register_blueprint(health.bp)

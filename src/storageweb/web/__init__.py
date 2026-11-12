"""Capa web (Flask).

* ``views/``: páginas HTML (auth, files, admin)
* ``api/``: API JSON (subidas por partes)
* ``context``: conexión a BD y ajustes por petición
* ``guards``: sesión, CSRF, control de acceso y cabeceras de seguridad
* ``templates/`` y ``static/``: frontend
"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    from .api import uploads
    from .views import admin, auth, files

    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(uploads.bp)

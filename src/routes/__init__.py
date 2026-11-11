"""Capa HTTP (Flask): blueprints de autenticación, archivos y administración."""
from __future__ import annotations

from flask import Flask

from . import admin, auth, files, uploads


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(uploads.bp)

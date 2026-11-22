"""Comprobación de salud para Docker, Kubernetes o balanceadores: GET /healthz (sin sesión, así que sin la versión:
servirle a cualquiera la versión le ayuda a buscar vulnerabilidades; está en /metrics y en Sistema → Información)."""
from __future__ import annotations

import sqlite3

from flask import Blueprint

from ..context import get_db
from . import json_api

bp = Blueprint("health", __name__)
json_api(bp)


@bp.route("/healthz")
def healthz():
    try:
        get_db().execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return {"status": "error", "detail": "database"}, 503
    return {"status": "ok"}

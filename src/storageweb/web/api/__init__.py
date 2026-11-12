"""API JSON. Los errores se devuelven como ``{"error": "..."}`` en vez de páginas HTML."""
from __future__ import annotations

from flask import Blueprint
from werkzeug.exceptions import HTTPException

from ...core.security import PathError
from ...core.storage import RootNotFound


def json_api(bp: Blueprint) -> Blueprint:
    """Registra en el blueprint manejadores de error que responden en JSON.

    Se aplican también a errores lanzados antes de la vista (p. ej. CSRF en ``before_request``),
    porque Flask elige el manejador según el blueprint de la URL solicitada.
    """
    @bp.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        return {"error": exc.description or exc.name}, exc.code

    @bp.errorhandler(PathError)
    @bp.errorhandler(RootNotFound)
    def _not_found(exc):
        return {"error": "No encontrado"}, 404

    return bp

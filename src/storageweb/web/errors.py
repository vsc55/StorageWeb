"""Páginas de error traducidas (las descripciones de Werkzeug están en inglés)."""
from __future__ import annotations

from flask import Flask, Response, render_template, request
from werkzeug.exceptions import HTTPException

from ..core.security import PathError
from ..core.storage import RootNotFound
from ..i18n import _, _l

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


def _render_error(code: int, name, description: str | None):
    return render_template("error.html", code=code, name=name, description=description), code


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if request.blueprint == "dav":  # WebDAV: el código en texto, sin la página (los clientes no la muestran)
            body = f"{exc.code} {exc.name}"
            if exc.description and exc.description != type(exc).description:
                body += f"\n{exc.description}"  # p. ej. por qué no cabe en la cuota (lo muestra la extensión)
            return Response(body, exc.code, mimetype="text/plain")
        # Si la descripción es la genérica de Werkzeug (en inglés), se usa la traducida
        description = exc.description
        if description == type(exc).description:
            description = ERROR_DESCRIPTIONS.get(exc.code, description)
        return _render_error(exc.code, ERROR_NAMES.get(exc.code, exc.name), description)

    @app.errorhandler(PathError)
    @app.errorhandler(RootNotFound)
    def handle_not_found(exc):
        message = str(exc) if isinstance(exc, RootNotFound) and str(exc) else _("The requested path does not exist.")
        return _render_error(404, ERROR_NAMES[404], message)

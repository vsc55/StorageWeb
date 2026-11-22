"""Páginas de error traducidas (las descripciones de Werkzeug están en inglés)."""
from __future__ import annotations

from flask import Flask, Response, g, render_template, request
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
# El título de la tarjeta (más claro que el nombre del código, que va abajo junto al número)
ERROR_TITLES = {
    400: _l("This request is not valid"),
    401: _l("You need to sign in"),
    403: _l("You cannot open this"),
    404: _l("We cannot find this page"),
    405: _l("This cannot be done here"),
    413: _l("This is too large"),
    429: _l("Too many attempts"),
    500: _l("Something went wrong"),
    503: _l("Under maintenance"),
}
ERROR_ICONS = {401: "lock", 403: "lock", 404: "compass", 429: "clock", 503: "clock"}
ERROR_DESCRIPTIONS = {
    404: _l("The requested page or file does not exist."),
    405: _l("This operation is not allowed here."),
    413: _l("The request exceeds the maximum size allowed by the server."),
    500: _l("Something went wrong on the server. Try again later."),
}


def _tips(code: int, signed_in: bool) -> list[tuple[str, str]]:
    """«Qué puedes hacer» con cada error: (icono, texto)."""
    if code == 404:
        return [("search", _("Check that the address is written correctly.")),
                ("home", _("Look for it from the start: it may have been moved or renamed.") if signed_in
                 else _("Sign in with your account and look for it from the start."))]
    if code in (401, 403):
        tips = [] if signed_in else [("user", _("Sign in with an account that has access."))]
        return tips + [("users", _("If you need it, ask an administrator for access."))]
    if code in (400, 405):
        return [("chevron-left", _("Go back and try again from the page."))]
    if code == 413:
        return [("upload", _("Send smaller files, or fewer at once."))]
    if code in (429, 503):
        return [("clock", _("Wait a few minutes before trying again."))]
    return [("sync", _("Try again in a few minutes.")),
            ("comment", _("If it keeps happening, tell the administrator when it happened: the server log has the "
                          "details."))]


def error_page(code: int, name, description: str | None) -> str:
    """La página de un error con la tarjeta de estado (templates/_status_frame.html): sin sesión, con el marco del
    inicio de sesión; con sesión, dentro de la aplicación."""
    signed_in = g.get("user") is not None
    return render_template("error.html", code=code, name=name, description=description,
                           title=ERROR_TITLES.get(code, name), icon=ERROR_ICONS.get(code, "alert"),
                           tips=_tips(code, signed_in))


def _render_error(code: int, name, description: str | None):
    return error_page(code, name, description), code


def _audit_denied(exc: HTTPException) -> None:
    """Un 403 de alguien con sesión (sin permiso, carpeta de solo lectura, sin acceso a la administración) queda
    en la auditoría como ``access_denied``. Los de una IP bloqueada no: ya consta el bloqueo y serían miles."""
    if exc.code != 403 or g.get("user") is None:
        return
    from .guards import audit_event  # noqa: PLC0415 (guards importa de aquí)
    try:
        audit_event("access_denied", request.path, f"{request.method}: {exc.description}"[:200])
    except Exception:  # noqa: BLE001 (la página de error sale igual)
        pass


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if request.blueprint == "dav":  # WebDAV: el código en texto, sin la página (los clientes no la muestran)
            body = f"{exc.code} {exc.name}"
            if exc.description and exc.description != type(exc).description:
                body += f"\n{exc.description}"  # p. ej. por qué no cabe en la cuota (lo muestra la extensión)
            return Response(body, exc.code, mimetype="text/plain")
        _audit_denied(exc)
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

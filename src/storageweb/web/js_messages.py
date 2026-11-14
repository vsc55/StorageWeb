"""Textos que usa el JavaScript del navegador (static/js/*.js).

Se marcan con ``N_`` para que la extracción los incluya en el catálogo. La plantilla base entrega
al navegador el diccionario ``{texto_fuente: traducción}`` como JSON (``<script type=
"application/json" id="i18n">``, permitido por la CSP porque no se ejecuta), y ``t()`` en JS lo usa.
"""
from __future__ import annotations

from ..i18n import N_, gettext

JS_MESSAGES = [
    N_("Are you sure?"),
    N_("New name:"),
    N_("Cancel the upload?"),
    N_("An upload is in progress"),
    N_("Network error."),
    N_("The part or the file is too large for the server."),
    N_("HTTP error %(status)s."),
    N_("These files exceed the maximum size allowed (%(max)s):"),
    N_("File %(index)s of %(total)s: %(name)s"),
    N_("Could not upload:"),
    N_("1 item selected"),
    N_("%(num)s items selected"),
    N_("Delete %(num)s items? This cannot be undone."),
    N_("%(count)s unsaved changes"),
    N_("%(count)s selected:"),
    N_("Copied"),
    N_("Waiting for you to sign in…"),
    N_("Signed in. Registering the application in Entra ID…"),
    N_("Nothing found for «%(query)s»."),
]


def catalog() -> dict[str, str]:
    return {message: gettext(message) for message in JS_MESSAGES}

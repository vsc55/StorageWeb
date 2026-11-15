"""Textos que usa el JavaScript del navegador (static/js/*.js).

Se marcan con ``N_`` para que la extracción los incluya en el catálogo. La plantilla base entrega
al navegador el diccionario ``{texto_fuente: traducción}`` como JSON (``<script type=
"application/json" id="i18n">``, permitido por la CSP porque no se ejecuta), y ``t()`` en JS lo usa.
"""
from __future__ import annotations

from ..i18n import N_, gettext

JS_MESSAGES = [
    N_("Are you sure?"),
    N_("Added: %(name)s"),
    N_("You cannot write in this folder."),
    N_("A folder cannot go inside itself."),
    N_("They are already in this folder: choose another one."),
    N_("Loading…"),
    N_("No subfolders."),
    N_("Could not read this folder."),
    N_("Move «%(name)s» to…"),
    N_("Move %(num)s items to…"),
    N_("Copy «%(name)s» to…"),
    N_("Copy %(num)s items to…"),
    N_("Move here"),
    N_("Copy here"),
    N_("read-only"),
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
    N_("default (save to apply)"),
    N_("here"),
    N_("Accept"),
    N_("Cancel"),
    N_("OK"),
    N_("unsaved"),
    N_("Unsaved changes"),
    N_("Discard"),
    N_("Save all"),
    N_("Discard the unsaved changes of the other pages?"),
    N_("Discard the %(count)s unsaved changes of every page?"),
    N_("1 unsaved change"),
    N_("Save"),
]


def catalog() -> dict[str, str]:
    return {message: gettext(message) for message in JS_MESSAGES}

"""Elementos con nombre. Listas (carpetas compartidas, ubicaciones de almacenamiento): buscar uno y sustituirlo o
añadirlo en una copia; los errores, con el mensaje de cada lista, los da quien llama. Y el nombre de una copia al
clonar (roles, grupos): «X (copia)», «X (copia 2)»…"""
from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterable

from ..i18n import _


def find(items: list[dict], name: str) -> dict | None:
    return next((item for item in items if item["name"] == name), None)


def replace(items: list[dict], original: str | None, item: dict, *, duplicate: Callable[[], Exception],
            missing: Callable[[], Exception]) -> list[dict]:
    """Copia de ``items`` con ``original`` sustituido por ``item``, o con ``item`` añadido si ``original`` es
    ``None``. Lanza ``duplicate()`` si se añade un nombre que ya está y ``missing()`` si ``original`` no está."""
    result = copy.deepcopy(items)
    if original is None:
        if find(result, item["name"]) is not None:
            raise duplicate()
        return result + [item]
    for i, current in enumerate(result):
        if current["name"] == original:
            result[i] = item
            return result
    raise missing()


def copy_label(label: str, taken: Iterable[str], max_len: int = 80) -> str:
    """El nombre de la copia de ``label`` que no esté en ``taken`` (sin distinguir mayúsculas): «X (copia)», o
    «X (copia 2)»… Clonar «X (copia)» propone «X (copia 2)», no «X (copia) (copia)»; el sufijo cabe siempre, aunque el
    nombre sea largo. ``""`` si no queda ninguno libre."""
    used = {str(t).lower() for t in taken}
    base = without_copy(label)
    for num in range(1, 1000):
        template = _("%(name)s (copy)", name="\0") if num == 1 else _("%(name)s (copy %(num)s)", name="\0", num=num)
        room = max_len - (len(template) - 1)
        name = template.replace("\0", base[:room].rstrip())
        if name.lower() not in used:
            return name
    return ""


def without_copy(label: str) -> str:
    """«X (copia)», «X (copia 3)», «X (copia) (copia)» → «X» (con los textos del idioma de la petición)."""
    patterns = []
    for template in (_("%(name)s (copy)", name="\0"), _("%(name)s (copy %(num)s)", name="\0", num="\1")):
        patterns.append(re.compile(re.escape(template).replace("\\\0", "\0").replace("\0", "(.+?)")
                                   .replace("\\\1", "\1").replace("\1", r"\d+"), re.IGNORECASE))
    while True:
        for pattern in patterns:
            found = pattern.fullmatch(label)
            if found and found.group(1).strip():
                label = found.group(1).strip()
                break
        else:
            return label


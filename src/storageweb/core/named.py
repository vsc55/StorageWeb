"""Listas de elementos con nombre (carpetas compartidas, ubicaciones de almacenamiento): buscar uno y sustituirlo o
añadirlo en una copia. Los errores, con el mensaje de cada lista, los da quien llama."""
from __future__ import annotations

import copy
from collections.abc import Callable


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

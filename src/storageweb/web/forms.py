"""Piezas comunes para leer formularios y volver a la página de origen."""
from __future__ import annotations

import re

from flask import flash, redirect, request, session

from .guards import safe_next


def split_list(value: str) -> list[str]:
    """Lista de un campo de texto separado por comas o líneas."""
    return [x.strip() for x in re.split(r"[,\n]", value or "") if x.strip()]


def checked(name: str) -> bool:
    """Si la casilla ``name`` del formulario está marcada."""
    return request.form.get(name) == "on"


def next_url(default: str) -> str:
    """``next`` (del formulario o de la URL) si es local; si no, ``default``."""
    target = request.form.get("next") or request.args.get("next")
    return safe_next(target) if target else default


def back(default: str):
    """Vuelve a ``next`` (del formulario o de la URL) si es local; si no, a ``default``."""
    return redirect(next_url(default))


def split_lines(name: str) -> list[str]:
    """Un campo del formulario con un valor por línea, sin las vacías."""
    return [line.strip() for line in request.form.get(name, "").splitlines() if line.strip()]


def uploaded(name: str):
    """El archivo elegido en el campo ``name`` del formulario, o ``None`` si no se eligió ninguno."""
    item = request.files.get(name)
    return item if item and item.filename else None


def choice(arg: str, allowed, default, *, type=None, source=None):
    """``?arg=`` si es uno de ``allowed``; si no, ``default`` (filtros, pestañas, orden…). ``type``: convertirlo
    (``int``); ``source``: otro sitio de donde leerlo (``request.values``). Sin recordarlo: para eso,
    :func:`remembered`."""
    source = request.args if source is None else source
    value = source.get(arg, default, type=type) if type else source.get(arg, default)
    return value if value in allowed else default


def page_of(total: int, size: int) -> tuple[int, int]:
    """``(página, páginas)`` de una lista de ``total`` elementos de ``size`` en ``size``: ``?page=`` acotada."""
    pages = max(-(-total // size), 1)
    return min(max(request.args.get("page", 1, type=int), 1), pages), pages


def pick(rows, wanted, key: str = "uid"):
    """En la vista Paneles, el elegido (``wanted``, por ``key``) o, si no está, el primero; ``None`` si no hay."""
    return next((r for r in rows if r[key] == wanted), None) or (rows[0] if rows else None)


def flash_outcome(done: str | None, errors: list[str]) -> None:
    """El resultado de una acción sobre varios elementos: lo hecho (ya traducido, o ``None``) y cada error."""
    if done:
        flash(done, "info")
    for error in errors:
        flash(error, "error")


def remembered(arg: str, key: str, allowed, default: str) -> str:
    """El valor de un filtro de la URL (``?arg=``) que se recuerda en la sesión: sin él en la URL (al recargar,
    al volver desde otra sección) vale el último elegido; uno que no está en ``allowed``, el de serie."""
    value = request.args.get(arg)
    if value in allowed:
        session[key] = value
        return value
    value = session.get(key)
    return value if value in allowed else default


VIEWS = ("list", "panel")


def use_view(key: str, view: str) -> None:
    """Usuarios, grupos y roles tienen dos vistas, Lista y Paneles: anota la que se está viendo (``key`` en la
    sesión: ``users_view``…) para volver a ella con :func:`last_view`."""
    session[key] = view


def last_view(key: str) -> str:
    """La última vista anotada con :func:`use_view` (``list`` o ``panel``); ``list`` si no hay ninguna."""
    view = session.get(key)
    return view if view in VIEWS else "list"

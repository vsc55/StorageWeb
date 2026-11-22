"""Piezas comunes para leer formularios y volver a la página de origen."""
from __future__ import annotations

import re

from flask import redirect, request

from .guards import safe_next


def split_list(value: str) -> list[str]:
    """Lista de un campo de texto separado por comas o líneas."""
    return [x.strip() for x in re.split(r"[,\n]", value or "") if x.strip()]


def checked(name: str) -> bool:
    """Si la casilla ``name`` del formulario está marcada."""
    return request.form.get(name) == "on"


def back(default: str):
    """Vuelve a ``next`` (del formulario o de la URL) si es local; si no, a ``default``."""
    target = request.form.get("next") or request.args.get("next")
    return redirect(safe_next(target) if target else default)


def remembered(arg: str, key: str, allowed, default: str) -> str:
    """El valor de un filtro de la URL (``?arg=``) que se recuerda en la sesión: sin él en la URL (al recargar,
    al volver desde otra sección) vale el último elegido; uno que no está en ``allowed``, el de serie."""
    from flask import request, session  # noqa: PLC0415
    value = request.args.get(arg)
    if value in allowed:
        session[key] = value
        return value
    value = session.get(key)
    return value if value in allowed else default

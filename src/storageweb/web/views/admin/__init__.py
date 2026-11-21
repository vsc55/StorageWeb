"""Administración (solo rol admin): un blueprint, un módulo por tema.

* ``overview`` — Resumen (avisos, tarjetas por zona, tareas frecuentes) y buscador (Ctrl+K)
* ``users``    — usuarios: lista y paneles, ficha, acciones en bloque
* ``audit``    — auditoría y exportación CSV
* ``browse``   — el selector de rutas de los campos (Examinar y autocompletado)

Los ajustes están en ``views/settings/``, los grupos en ``views/groups.py`` y las carpetas
compartidas en ``views/access.py``.
"""
from __future__ import annotations

from flask import Blueprint

from ....core import accounts
from ....core.permissions import PERMISSION_LABELS, ROLE_LABELS
from ....settings import ROLES

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.context_processor
def _labels():
    return {"ROLE_LABELS": ROLE_LABELS, "SOURCE_LABELS": accounts.source_labels(),
            "PERMISSION_LABELS": PERMISSION_LABELS, "ROLES": ROLES}


from . import audit, browse, overview, users  # noqa: E402,F401  (registran sus rutas)

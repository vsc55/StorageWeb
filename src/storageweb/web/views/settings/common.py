"""Piezas compartidas por las páginas de ajustes."""
from __future__ import annotations

from flask import g, request

from ....i18n import _
from ....settings import ConfigError, merge_overrides, runtime_view
from ...context import get_db, invalidate_settings, network_diagnosis, runtime, settings
from ...forms import back, checked, split_list  # noqa: F401  (las usan los módulos de ajustes)


def form_int(name: str, field: str, label: str) -> int:
    """Número del formulario; :class:`ConfigError` (junto al campo ``field``) si no lo es."""
    if name not in request.form and runtime().lock_of(field):
        return 0  # campo bloqueado (desactivado en el formulario): no se guarda
    try:
        return int(request.form.get(name, ""))
    except ValueError as exc:
        raise ConfigError(_("%(field)s must be a number", field=label), field) from exc


def save_partial(partial_builder, strict: bool = False) -> tuple[dict | None, ConfigError | None]:
    """Combina lo del formulario con los ajustes efectivos, valida y guarda. Devuelve (vista, error).

    Los campos bloqueados (config.json o entorno) no se guardan. Con ``strict`` (cambios hechos por
    código: logo, Entra ID…) intentar cambiar uno es un error en vez de ignorarse.
    """
    draft = None
    try:
        base = runtime_view(settings())  # lo que había en pantalla: solo se guarda lo que cambia sobre esto
        draft = merge_overrides(base, partial_builder())
        runtime().save(get_db(), draft, g.user["username"], strict=strict, base=base)
    except ConfigError as exc:
        return draft, exc
    invalidate_settings()
    return draft, None


def network_context(cfg: dict) -> dict:
    return network_diagnosis(cfg)

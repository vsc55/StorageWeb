"""Comprobaciones de valores de configuración, para el cargador y para las que declaran los proveedores.

Cada función recibe el valor y la ruta del campo (``auth.entra.scopes``) y devuelve el valor
normalizado o lanza :class:`ConfigError` con esa ruta, para que la web muestre el error en su campo.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..i18n import _
from .defaults import ROLES
from .errors import ConfigError


def str_list(value, path: str, *, lower: bool = False) -> list[str]:
    """Lista de textos; admite también un texto separado por comas o espacios."""
    if isinstance(value, str):
        value = [x for x in re.split(r"[,\s]+", value) if x]
    if not isinstance(value, list):
        raise ConfigError(_("%(field)s must be a list", field=path), path)
    items = [str(x).strip() for x in value if str(x).strip()]
    return [x.lower() for x in items] if lower else items


def positive_int(value, path: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(_("%(field)s must be an integer", field=path), path) from exc
    if number < 1:
        raise ConfigError(_("%(field)s must be greater than 0", field=path), path)
    return number


def iso_datetime(value, path: str) -> str:
    """Fecha u hora ISO 8601 normalizada (UTC, con zona), o vacío."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(_("%(field)s must be a date like 2027-11-13", field=path), path) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def one_of(value, values, path: str):
    if value not in values:
        raise ConfigError(_("%(field)s must be one of: %(values)s", field=path, values=", ".join(values)), path)
    return value


def role_mappings(value, path: str) -> dict[str, str]:
    """``{grupo: rol}`` con los grupos en minúsculas y roles válidos."""
    if not isinstance(value, dict):
        raise ConfigError(_("%(field)s must be an object {group: role}", field=path), path)
    mappings = {}
    for key, role in value.items():
        if role not in ROLES:
            raise ConfigError(_("Invalid role %(role)s in role_mappings (use %(values)s)", role=repr(role),
                                values=", ".join(ROLES)), path)
        mappings[str(key).strip().lower()] = role
    return mappings

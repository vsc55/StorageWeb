"""Comprobaciones de valores de configuración, para el cargador y para las que declaran los proveedores.

Cada función recibe el valor y la ruta del campo (``auth.entra.scopes``) y devuelve el valor
normalizado o lanza :class:`ConfigError` con esa ruta, para que la web muestre el error en su campo.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone

from ..i18n import _
from .defaults import ROLES, SYSLOG_PORTS
from .errors import ConfigError


# ``path`` es lo que se nombra en el mensaje; ``field`` (si es otra) la ruta junto a la que la web enseña el error

def str_list(value, path: str, *, lower: bool = False, field: str | None = None) -> list[str]:
    """Lista de textos; admite también un texto separado por comas o espacios."""
    if isinstance(value, str):
        value = [x for x in re.split(r"[,\s]+", value) if x]
    if not isinstance(value, list):
        raise ConfigError(_("%(field)s must be a list", field=path), field or path)
    items = [str(x).strip() for x in value if str(x).strip()]
    return [x.lower() for x in items] if lower else items


def _integer(value, path: str, field: str | None) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(_("%(field)s must be an integer", field=path), field or path) from exc


def positive_int(value, path: str, field: str | None = None) -> int:
    number = _integer(value, path, field)
    if number < 1:
        raise ConfigError(_("%(field)s must be greater than 0", field=path), field or path)
    return number


def non_negative_int(value, path: str, field: str | None = None) -> int:
    number = _integer(value, path, field)
    if number < 0:
        raise ConfigError(_("%(field)s cannot be negative", field=path), field or path)
    return number


def int_range(value, low: int, high: int, path: str, field: str | None = None) -> int:
    """Un entero entre ``low`` y ``high`` (ambos incluidos)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = None
    if number is None or not low <= number <= high:
        raise ConfigError(_("%(field)s must be a whole number between %(low)s and %(high)s", field=path, low=low,
                            high=high), field or path) from None
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


def role_key(value) -> bool:
    """Si ``value`` puede ser un rol: uno de serie o la clave de uno propio (core/roles.py; si ya no existe, al
    entrar cuenta como Usuario)."""
    return value in ROLES or bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", str(value or "")))


def role_mappings(value, path: str) -> dict[str, str]:
    """``{grupo: rol}`` con los grupos en minúsculas y roles válidos."""
    if not isinstance(value, dict):
        raise ConfigError(_("%(field)s must be an object {group: role}", field=path), path)
    mappings = {}
    for key, role in value.items():
        if not role_key(role):
            raise ConfigError(_("Invalid role %(role)s in role_mappings (use %(values)s or the key of a role)",
                                role=repr(role), values=", ".join(ROLES)), path)
        mappings[str(key).strip().lower()] = role
    return mappings


def syslog_target(url: str) -> tuple[str, str, int] | None:
    """``udp://host:514`` → ``("udp", "host", 514)`` (sin puerto, el de serie del esquema); ``None`` si no es un
    destino syslog válido (esquema udp/tcp/tls, un host, sin ruta y un puerto de 1 a 65535)."""
    parts = urllib.parse.urlsplit(str(url or "").strip())
    try:
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme not in SYSLOG_PORTS or not parts.hostname or parts.path not in ("", "/")
            or (port is not None and not 1 <= port <= 65535)):
        return None
    return parts.scheme, parts.hostname, port or SYSLOG_PORTS[parts.scheme]


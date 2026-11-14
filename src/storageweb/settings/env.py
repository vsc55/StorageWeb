"""Ajustes fijados por variables de entorno: ``STORAGEWEB_`` + la ruta en mayúsculas con ``__`` entre niveles.

``STORAGEWEB_AUTH__ENTRA__CLIENT_ID``; las listas y los objetos van en JSON. Se mantienen los nombres
cortos de Docker (``ENV_ALIASES``).
"""
from __future__ import annotations

import json
import os
import re

from ..i18n import _
from .defaults import DEFAULTS
from .errors import ConfigError
from .layers import _set, get_path, leaf_paths

ENV_PREFIX = "STORAGEWEB_"
# Nombres cortos de siempre (Docker) para algunos campos


ENV_ALIASES = {
    "STORAGEWEB_PUBLIC_URL": "network.public_url",
    "STORAGEWEB_PORT": "server.port",
    "STORAGEWEB_BEHIND_PROXY": "server.behind_proxy",
    "STORAGEWEB_PROXY_HOPS": "server.proxy_hops",
    "STORAGEWEB_MAX_UPLOAD_MB": "server.max_upload_mb",
    "STORAGEWEB_COOKIE_SECURE": "session.cookie_secure",
}
_TRUE, _FALSE = ("1", "true", "yes", "on"), ("0", "false", "no", "off", "")


def env_name(dotted: str) -> str:
    """Variable de entorno de un campo: ``auth.entra.client_id`` → ``STORAGEWEB_AUTH__ENTRA__CLIENT_ID``."""
    return ENV_PREFIX + dotted.upper().replace(".", "__")


def setting_paths() -> list[str]:
    """Rutas de todos los campos configurables (las listas y los ``LEAF_PATHS`` son un único campo)."""
    return sorted(leaf_paths(DEFAULTS))


def _env_value(dotted: str, name: str, raw: str):
    default = get_path(DEFAULTS, dotted)
    text = raw.strip()
    if isinstance(default, bool):
        if text.lower() not in _TRUE + _FALSE:
            raise ConfigError(_("%(name)s must be true or false", name=name), dotted)
        return text.lower() in _TRUE
    if isinstance(default, int):
        try:
            return int(text)
        except ValueError as exc:
            raise ConfigError(_("%(name)s must be an integer", name=name), dotted) from exc
    if isinstance(default, (list, dict)):
        if text.startswith(("[", "{")):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigError(_("%(name)s is not valid JSON: %(error)s", name=name, error=exc), dotted) from exc
        if isinstance(default, list):
            return [x for x in re.split(r"[,\s]+", text) if x]
        raise ConfigError(_("%(name)s must be a JSON object", name=name), dotted)
    return raw


def env_config(environ=None) -> dict:
    """Ajustes fijados por variables de entorno, como árbol (``{"auth": {"entra": {...}}}``).

    Solo cuentan las variables de campos conocidos; las demás ``STORAGEWEB_*`` (``STORAGEWEB_CONFIG``,
    ``STORAGEWEB_LANG``, las del admin de Docker…) se ignoran.
    """
    environ = os.environ if environ is None else environ
    known = {env_name(p): p for p in setting_paths()}
    known.update(ENV_ALIASES)
    out: dict = {}
    for name, raw in environ.items():
        dotted = known.get(name.upper())
        if dotted:
            _set(out, tuple(dotted.split(".")), _env_value(dotted, name.upper(), raw))
    return out

"""Página «Inicio de sesión»: una tarjeta por método (``providers.AuthMethod``), sin saber cuáles hay.

Cada método se pinta con ``admin/settings/auth/<método>.html`` (o, si no tiene, con
``_generic.html``, que muestra los campos de su configuración) y su formulario se lee con:

- el lector que registre su módulo web con :func:`form_parser` (Entra ID: ``entra.py``), o
- el genérico, que sale de sus valores por defecto: casillas para los booleanos, listas separadas por
  comas, números y textos (``<método>_<campo>`` en el formulario; un secreto vacío se conserva).

:func:`page_context` añade variables para su tarjeta (estado de la comprobación, caducidad…).
"""
from __future__ import annotations

from collections.abc import Callable

from flask import request

from .... import providers
from ....providers import AuthMethod
from .common import checked, form_int, split_list

_PARSERS: dict[str, Callable[[AuthMethod], dict]] = {}
_CONTEXTS: dict[str, Callable[[dict], dict]] = {}


def form_parser(key: str):
    """Registra ``fn(method) -> dict`` como lector del apartado ``auth.<key>`` del formulario."""
    def decorate(fn):
        _PARSERS[key] = fn
        return fn
    return decorate


def page_context(key: str):
    """Registra ``fn(cfg) -> dict`` con variables para la tarjeta del método."""
    def decorate(fn):
        _CONTEXTS[key] = fn
        return fn
    return decorate


def generic_parser(method: AuthMethod) -> dict:
    """Lee los campos de primer nivel del método a partir del tipo de su valor por defecto."""
    secrets = set(method.config.secrets)
    out = {}
    for name, default in method.config.defaults.items():
        field = f"{method.key}_{name}"
        if isinstance(default, bool):
            out[name] = checked(field)
        elif isinstance(default, list):
            out[name] = split_list(request.form.get(field, ""))
        elif isinstance(default, int):
            out[name] = form_int(field, f"auth.{method.key}.{name}", str(method.config.fields[name].label or name))
        elif isinstance(default, str):
            value = request.form.get(field, "").strip()
            if name in secrets and not value:
                continue  # secreto vacío: se conserva el guardado
            out[name] = value or default
        # los diccionarios y demás no se editan con el formulario genérico
    return out


def parse() -> dict:
    return {"auth": {m.key: _PARSERS.get(m.key, generic_parser)(m) for m in providers.methods()}}


def context(cfg: dict) -> dict:
    ctx: dict = {"auth_methods": providers.methods()}
    for method in providers.methods():
        if method.key in _CONTEXTS:
            ctx.update(_CONTEXTS[method.key](cfg))
    return ctx

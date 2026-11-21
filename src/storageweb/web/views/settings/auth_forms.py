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
from ....core.mfa import webauthn
from ....db.repositories import mfa as mfa_repo
from ....i18n import _l
from ....providers import AuthMethod
from ....settings.defaults import MFA_POLICIES
from ...context import get_db
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
    return {"auth": {m.key: _PARSERS.get(m.key, generic_parser)(m) for m in providers.methods()},
            # La política de la verificación en dos pasos va en esta página (es del inicio de sesión)
            "security": {"mfa_required": request.form.get("mfa_required", "off"), "passkeys": checked("passkeys")}}


MFA_POLICY_LABELS = dict(zip(MFA_POLICIES, (_l("Nobody: optional for everyone"), _l("Administrators"),
                                            _l("All accounts that sign in with a password"))))


def context(cfg: dict) -> dict:
    password_methods = [m.key for m in providers.methods() if m.password and not m.sso]
    marks = ",".join("?" * len(password_methods)) or "''"
    with_password = get_db().execute(f"SELECT id FROM users WHERE enabled = 1 AND source IN ({marks})",  # noqa: S608
                                     password_methods).fetchall()
    enrolled = mfa_repo.enrolled_ids(get_db())
    ctx: dict = {"auth_methods": providers.methods(), "mfa_policies": list(MFA_POLICY_LABELS.items()),
                 "passkey_rp": webauthn.scope_from(cfg["network"].get("public_url", ""))[0],
                 "mfa_counts": {"total": len(with_password),
                                "enrolled": sum(1 for r in with_password if r["id"] in enrolled)}}
    for method in providers.methods():
        if method.key in _CONTEXTS:
            ctx.update(_CONTEXTS[method.key](cfg))
    return ctx

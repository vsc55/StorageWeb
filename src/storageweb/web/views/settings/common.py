"""Piezas compartidas por las páginas de ajustes."""
from __future__ import annotations

from flask import g, request

from ....settings import ConfigError, merge_overrides, runtime_view
from ...context import external_url, get_db, invalidate_settings, network_diagnosis, runtime, settings
from ...forms import back, checked, split_list  # noqa: F401  (las usan los módulos de ajustes)


def entra_connection() -> dict:
    f = request.form
    data = {"tenant_id": f.get("entra_tenant_id", "").strip(), "client_id": f.get("entra_client_id", "").strip(),
            "redirect_uri": f.get("entra_redirect_uri", "").strip()}
    if f.get("entra_client_secret", "").strip():  # vacío = conservar el actual
        data["client_secret"] = f["entra_client_secret"].strip()
    return data


def redirect_uri(ecfg: dict) -> str:
    return ecfg.get("redirect_uri") or external_url("auth.entra_callback")


def save_partial(partial_builder, strict: bool = False) -> tuple[dict | None, ConfigError | None]:
    """Combina lo del formulario con los ajustes efectivos, valida y guarda. Devuelve (vista, error).

    Los campos bloqueados (config.json o entorno) no se guardan. Con ``strict`` (cambios hechos por
    código: logo, Entra ID…) intentar cambiar uno es un error en vez de ignorarse.
    """
    draft = None
    try:
        draft = merge_overrides(runtime_view(settings()), partial_builder())
        runtime().save(get_db(), draft, g.user["username"], strict=strict)
    except ConfigError as exc:
        return draft, exc
    invalidate_settings()
    return draft, None


def network_context(cfg: dict) -> dict:
    return network_diagnosis(cfg)

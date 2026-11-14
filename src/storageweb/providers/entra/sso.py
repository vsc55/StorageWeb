"""Implementaciones del SSO de Entra ID: ``oauth2`` (propia, por defecto) y ``msal`` (de Microsoft)."""
from __future__ import annotations

from ..base import SSOError, SSOProvider
from .msal import MsalProvider
from .oauth2 import OAuth2Provider

SSO_PROVIDERS: dict[str, type[SSOProvider]] = {
    OAuth2Provider.name: OAuth2Provider,
    MsalProvider.name: MsalProvider,
}


def get_sso_provider(ecfg: dict, name: str | None = None) -> SSOProvider:
    cls = SSO_PROVIDERS.get(name or ecfg["provider"])
    if cls is None:
        raise SSOError("unknown_provider", f"Proveedor SSO desconocido: {name or ecfg['provider']}")
    return cls(ecfg)

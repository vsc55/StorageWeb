"""Proveedores de autenticación, uno por carpeta.

* ``local/`` — contraseñas de usuarios locales (SQLite)
* ``pam/``   — usuarios del sistema operativo
* ``entra/`` — Microsoft Entra ID: SSO (``oauth2`` propio, por defecto, y ``msal``), comprobación,
  directorio de grupos y registro de la aplicación

Para añadir otro SSO, crea su carpeta con una subclase de ``SSOProvider`` y regístrala aquí.
"""
from __future__ import annotations

from .base import SSOError, SSOProvider
from .entra.msal import MsalProvider
from .entra.oauth2 import OAuth2Provider

SSO_PROVIDERS: dict[str, type[SSOProvider]] = {
    OAuth2Provider.name: OAuth2Provider,
    MsalProvider.name: MsalProvider,
}


def get_sso_provider(ecfg: dict, name: str | None = None) -> SSOProvider:
    cls = SSO_PROVIDERS.get(name or ecfg["provider"])
    if cls is None:
        raise SSOError("unknown_provider", f"Proveedor SSO desconocido: {name or ecfg['provider']}")
    return cls(ecfg)


__all__ = ["SSOError", "SSOProvider", "SSO_PROVIDERS", "get_sso_provider", "OAuth2Provider",
           "MsalProvider"]

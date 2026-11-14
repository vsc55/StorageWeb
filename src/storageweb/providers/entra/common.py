"""Lo común de Microsoft Entra ID: endpoints a partir del tenant y cierre de sesión."""
from __future__ import annotations

import urllib.parse

from ..base import SSOProvider

MS_LOGIN = "https://login.microsoftonline.com"
MULTI_TENANT = {"common", "organizations", "consumers"}


def endpoints(ecfg: dict) -> dict:
    """Endpoints OAuth2 de Entra ID calculados a partir del tenant (o los configurados)."""
    tenant = ecfg.get("tenant_id", "")
    return {
        "authorize": ecfg.get("authorize_url") or f"{MS_LOGIN}/{tenant}/oauth2/v2.0/authorize",
        "token": ecfg.get("token_url") or f"{MS_LOGIN}/{tenant}/oauth2/v2.0/token",
        "issuer": ecfg.get("issuer") or f"{MS_LOGIN}/{tenant}/v2.0",
        "logout": ecfg.get("logout_url") or f"{MS_LOGIN}/{tenant}/oauth2/v2.0/logout",
    }


class EntraProvider(SSOProvider):
    """Base de los proveedores SSO de Entra ID (``oauth2`` y ``msal``)."""

    def logout_url(self, post_logout_redirect_uri: str) -> str:
        query = urllib.parse.urlencode({"post_logout_redirect_uri": post_logout_redirect_uri})
        return f"{endpoints(self.cfg)['logout']}?{query}"

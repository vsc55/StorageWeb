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


GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"


def custom_endpoints(ecfg: dict) -> bool:
    """Si se usan direcciones propias (otro proveedor OIDC) en vez de las de Microsoft: entonces no hay Graph."""
    return any(ecfg.get(k) for k in ("authorize_url", "token_url", "issuer"))


def app_token_request(ecfg: dict, timeout: float) -> dict:
    """La respuesta de Microsoft al pedir un token de la aplicación (``client_credentials``) para Graph."""
    from . import oauth2  # noqa: PLC0415 (oauth2 importa este módulo)
    return oauth2._http_post(endpoints(ecfg)["token"], {  # noqa: SLF001
        "grant_type": "client_credentials", "client_id": ecfg.get("client_id", ""),
        "client_secret": ecfg["client_secret"], "scope": GRAPH_DEFAULT_SCOPE}, timeout)


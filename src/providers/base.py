"""Interfaz común de los proveedores SSO."""
from __future__ import annotations

import urllib.parse

MS_LOGIN = "https://login.microsoftonline.com"
BASE_SCOPES = ["openid", "profile", "email"]
MULTI_TENANT = {"common", "organizations", "consumers"}


class SSOError(Exception):
    def __init__(self, code: str, description: str = ""):
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code
        self.description = description


def endpoints(ecfg: dict) -> dict:
    """Endpoints OAuth2 de Entra ID calculados a partir del tenant (o los configurados)."""
    tenant = ecfg.get("tenant_id", "")
    return {
        "authorize": ecfg.get("authorize_url") or f"{MS_LOGIN}/{tenant}/oauth2/v2.0/authorize",
        "token": ecfg.get("token_url") or f"{MS_LOGIN}/{tenant}/oauth2/v2.0/token",
        "issuer": ecfg.get("issuer") or f"{MS_LOGIN}/{tenant}/v2.0",
        "logout": ecfg.get("logout_url") or f"{MS_LOGIN}/{tenant}/oauth2/v2.0/logout",
    }


class SSOProvider:
    """Un proveedor SSO implementa el flujo Authorization Code en dos pasos.

    ``begin`` devuelve la URL a la que redirigir al usuario y un ``flow`` (dict serializable a
    JSON) que se guarda en la sesión; ``complete`` recibe ese ``flow`` y los parámetros del
    callback y devuelve los claims del id_token ya validados.
    """

    name = ""

    def __init__(self, ecfg: dict):
        self.cfg = ecfg

    def begin(self, redirect_uri: str) -> tuple[str, dict]:
        raise NotImplementedError

    def complete(self, flow: dict, args: dict) -> dict:
        raise NotImplementedError

    def logout_url(self, post_logout_redirect_uri: str) -> str:
        query = urllib.parse.urlencode({"post_logout_redirect_uri": post_logout_redirect_uri})
        return f"{endpoints(self.cfg)['logout']}?{query}"

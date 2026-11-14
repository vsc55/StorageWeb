"""Proveedor SSO basado en MSAL (librería oficial de Microsoft).

MSAL realiza descubrimiento de la autoridad por red al crear la aplicación, por lo que
requiere conexión con login.microsoftonline.com también al iniciar el login.
"""
from __future__ import annotations

from ..base import BASE_SCOPES, SSOError
from .common import MS_LOGIN, EntraProvider


def _msal_app(ecfg: dict):
    import msal

    return msal.ConfidentialClientApplication(
        ecfg["client_id"],
        authority=f"{MS_LOGIN}/{ecfg['tenant_id']}",
        client_credential=ecfg["client_secret"],
    )


class MsalProvider(EntraProvider):
    name = "msal"

    def begin(self, redirect_uri: str) -> tuple[str, dict]:
        # MSAL añade openid/profile/offline_access por su cuenta y no admite que se pasen
        scopes = [s for s in self.cfg.get("scopes", []) if s not in BASE_SCOPES + ["offline_access"]]
        flow = _msal_app(self.cfg).initiate_auth_code_flow(scopes=scopes, redirect_uri=redirect_uri,
                                                           prompt="select_account")
        return flow["auth_uri"], {"provider": self.name, "msal": flow}

    def complete(self, flow: dict, args: dict) -> dict:
        try:
            result = _msal_app(self.cfg).acquire_token_by_auth_code_flow(flow["msal"], args)
        except ValueError as exc:
            raise SSOError("invalid_state", str(exc)) from exc
        if "error" in result:
            raise SSOError(str(result["error"]), str(result.get("error_description", "")))
        claims = result.get("id_token_claims")
        if not claims:
            raise SSOError("missing_id_token", "MSAL no devolvió id_token_claims")
        return claims

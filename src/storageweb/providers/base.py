"""Interfaz común de los proveedores SSO (independiente del proveedor de identidad)."""
from __future__ import annotations

BASE_SCOPES = ["openid", "profile", "email"]


class SSOError(Exception):
    def __init__(self, code: str, description: str = ""):
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code
        self.description = description


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
        """URL de cierre de sesión en el proveedor (vacía si no tiene)."""
        return ""

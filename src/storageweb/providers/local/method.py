"""Método de inicio de sesión «local»: usuario y contraseña guardados en StorageWeb."""
from __future__ import annotations

from ...i18n import _l
from ...settings.auth_methods import AuthConfig
from ...settings.fields import Field
from ..base import AuthMethod, Identity
from . import verify


class LocalMethod(AuthMethod):
    key = "local"
    label = _l("Local")
    description = _l("User name and password stored in StorageWeb")
    icon = "lock"
    order = 10
    password = True
    stores_password = True
    config = AuthConfig(
        key="local",
        defaults={"enabled": True},
        fields={"enabled": Field(doc="Permitir el inicio de sesión de usuarios locales (guardados en SQLite).",
                                 label=_l("Local users"), page="auth", words="local contraseña password login")},
        order=10,
    )

    def verify(self, section: dict, user, username: str, password: str) -> Identity | None:
        if user is None or not verify(user["password_hash"], password):
            return None
        return Identity(username=user["username"])

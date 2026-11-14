"""Método de inicio de sesión «pam»: usuarios del sistema operativo (Linux/macOS)."""
from __future__ import annotations

import sys

from ...i18n import _, _l
from ...settings import checks
from ...settings.auth_methods import AuthConfig
from ...settings.errors import ConfigError
from ...settings.fields import Field
from ..base import AuthMethod, Identity
from . import authenticate, system_home


def _validate(section: dict, cfg: dict) -> None:
    section["service"] = str(section.get("service") or "login").strip() or "login"
    section["allowed_groups"] = checks.str_list(section["allowed_groups"], "auth.pam.allowed_groups", lower=True)
    section["admin_groups"] = checks.str_list(section["admin_groups"], "auth.pam.admin_groups", lower=True)
    section["use_system_home"] = bool(section["use_system_home"])
    if section["enabled"] and sys.platform == "win32":
        raise ConfigError(_("auth.pam is not available on Windows"), "auth.pam.enabled")


class PamMethod(AuthMethod):
    key = "pam"
    label = _l("System (PAM)")
    description = _l("Accounts of the Linux/macOS server")
    icon = "monitor"
    order = 20
    password = True
    provisions = True
    external_groups = True
    group_hint = _l("Members of a group of the server.")
    group_id_help = _l("System: group name.")
    config = AuthConfig(
        key="pam",
        defaults={
            # Usuarios del sistema operativo (solo Linux/macOS, requiere python-pam)
            "enabled": False,
            "service": "login",
            # Si no está vacío, solo pueden entrar miembros de estos grupos del SO
            "allowed_groups": [],
            # Miembros de estos grupos del SO obtienen el rol admin
            "admin_groups": [],
            # True = usar el home real del usuario (/home/usuario) en vez de home_template
            "use_system_home": False,
        },
        fields={
            "enabled": Field(
                doc="Permitir el inicio de sesión de usuarios del sistema operativo mediante PAM (Linux/macOS).",
                label=_l("System users (PAM)"), page="auth", words="pam linux sistema system"),
            "service": Field(doc="Servicio PAM que se usa para autenticar.", label=_l("PAM service"), page="auth"),
            "allowed_groups": Field(doc="Si no está vacío, solo entran los miembros de estos grupos del sistema.",
                                    label=_l("Allowed groups"), page="auth", words="pam grupos permitidos"),
            "admin_groups": Field(doc="Los miembros de estos grupos del sistema reciben el rol `admin`.",
                                  label=_l("Groups with the administrator role"), page="auth",
                                  words="pam administradores admins"),
            "use_system_home": Field(
                doc="Usar el home real del usuario (`/home/<usuario>`) en vez de `storage.home_template`.",
                label=_l("Use the system home folder (/home/user)"), page="auth"),
        },
        validate=_validate,
        order=20,
    )

    def verify(self, section: dict, user, username: str, password: str) -> Identity | None:
        groups = authenticate(section, username, password)
        if groups is None:
            return None
        admin_groups = set(section["admin_groups"])
        # Sin grupos de administradores, PAM no decide el rol (las cuentas nuevas son «user»)
        role = ("admin" if admin_groups.intersection(groups) else "user") if admin_groups else None
        home = system_home(username) if section["use_system_home"] else None
        return Identity(username=username, groups=groups, role=role, home=home)

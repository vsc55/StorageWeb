"""Interfaces de los proveedores: métodos de inicio de sesión (:class:`AuthMethod`) y protocolos SSO.

Un **método de inicio de sesión** (local, PAM, Entra ID…) es una subclase de :class:`AuthMethod` en
su carpeta ``providers/<método>/``: declara su configuración (``config``, un
``settings.auth_methods.AuthConfig``), qué sabe hacer (contraseña o SSO, grupos externos…) y lo
específico de su proveedor. ``providers.discover()`` los encuentra solos; el resto del código
(cuentas, grupos, login, Resumen, CLI, ajustes) solo usa esta interfaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..settings.auth_methods import AuthConfig

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


class AuthDenied(Exception):
    """El proveedor reconoce a la persona pero no la deja entrar (tenant, grupo…). ``message`` es para ella."""

    def __init__(self, message: str, code: str = "denied"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Identity:
    """Quién es, según el proveedor. ``role`` solo si el proveedor lo decide (PAM: grupos de admins)."""
    username: str
    external_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    groups: list[str] = field(default_factory=list)
    role: str | None = None
    home: str | None = None


@dataclass(frozen=True)
class Notice:
    """Aviso para el Resumen (``core.alerts``); se resuelve en la página de inicio de sesión."""
    level: str          # danger | warn | info
    key: str
    title: str
    detail: str
    action: str
    anchor: str = ""


@dataclass(frozen=True)
class LoginButton:
    label: str
    css_class: str = ""
    icon: str = ""      # símbolo del sprite de iconos (``#i-<icon>``), si lo hay


class GroupDirectory:
    """Directorio de grupos del proveedor: nombres legibles y búsqueda (opcional)."""

    def configured(self) -> bool:
        return False

    def names_for(self, ids) -> dict[str, str]:
        return {}

    def search(self, text: str) -> list[dict]:
        """``[{"id", "name"}]``."""
        return []


class AuthMethod:
    """Un método de inicio de sesión. Las subclases con ``key`` se registran solas (``providers.discover``)."""

    key: str = ""                 # auth.<key> y users.source / groups.source
    label: object = ""            # «Local», «Sistema (PAM)», «Entra ID»
    description: object = ""      # una línea para la página de ajustes
    icon: str = "lock"            # icono de su tarjeta en los ajustes
    config: AuthConfig | None = None
    order: int = 50

    # Qué sabe hacer
    password: bool = False        # entra con el formulario de usuario y contraseña
    sso: bool = False             # entra por redirección al proveedor (begin/complete)
    stores_password: bool = False # la contraseña se guarda en StorageWeb (se puede cambiar aquí)
    provisions: bool = False      # (contraseña) crea la cuenta en el primer inicio de sesión correcto
    external_groups: bool = False # trae grupos del proveedor (pertenencias sincronizadas)
    lowercase_usernames: bool = False

    # Textos de los grupos de este origen (Personas → Grupos)
    group_hint: object = ""       # «Sincronizado en cada inicio de sesión desde…»
    group_id_help: object = ""    # qué poner como identificador del grupo externo

    def section(self, cfg: dict) -> dict:
        return cfg["auth"][self.key]

    def enabled(self, cfg: dict) -> bool:
        return bool(self.section(cfg).get("enabled"))

    # --- contraseña
    def verify(self, section: dict, user, username: str, password: str) -> Identity | None:
        """Comprueba la contraseña. ``user`` es la cuenta si ya existe (o ``None``)."""
        raise NotImplementedError

    # --- SSO
    def login_button(self, section: dict) -> LoginButton:
        return LoginButton(str(self.label))

    def begin(self, section: dict, redirect_uri: str) -> tuple[str, dict]:
        """URL del proveedor y ``flow`` (dict serializable) que se guarda en la sesión."""
        raise NotImplementedError

    def complete(self, section: dict, flow: dict, args: dict) -> Identity:
        """Valida la vuelta del proveedor. :class:`SSOError` (protocolo) o :class:`AuthDenied`."""
        raise NotImplementedError

    def redirect_uri(self, section: dict) -> str:
        """Dirección de vuelta configurada; vacía = la calcula la web."""
        return section.get("redirect_uri", "")

    def logout_url(self, section: dict, post_logout_redirect_uri: str) -> str:
        """Cierre de sesión también en el proveedor (vacío = no)."""
        return ""

    # --- administración
    def notices(self, section: dict) -> list[Notice]:
        """Avisos para el Resumen (secretos que caducan…)."""
        return []

    def network_notes(self, section: dict, public_url: str) -> list[tuple[str, str]]:
        """Avisos del diagnóstico de red (direcciones de vuelta que no usan la pública…)."""
        return []

    def directory(self, section: dict) -> GroupDirectory | None:
        return None

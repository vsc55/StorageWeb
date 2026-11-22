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
from ..settings.errors import UserError

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


class AuthDenied(UserError):
    """El proveedor reconoce a la persona pero no la deja entrar (tenant, grupo…). ``message`` es para ella."""

    def __init__(self, message: str, code: str = "denied"):
        super().__init__(message)
        self.code = code


@dataclass
class Identity:
    """Quién es, según el proveedor. ``role`` solo si el proveedor lo decide (PAM: grupos de admins)."""
    username: str
    external_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    # None = no se sabe (p. ej. demasiados grupos para el token y no se pudieron leer): se conservan los de antes
    groups: list[str] | None = field(default_factory=list)
    role: str | None = None
    home: str | None = None
    # Sesión en el proveedor (claim «sid»): su cierre de sesión de canal frontal cierra la de StorageWeb
    session_id: str | None = None
    # Permisos (scopes) que el proveedor dice haber concedido en este inicio de sesión; None si no lo dice.
    # Se guarda el último por método para que la comprobación de la conexión pueda decir si faltan.
    granted_scopes: list[str] | None = None


@dataclass(frozen=True)
class DirectoryUser:
    """Estado de una cuenta en el directorio del proveedor (revisión periódica, sin que la persona entre)."""
    exists: bool
    enabled: bool = True
    allowed: bool = True          # cumple los grupos permitidos del método
    groups: list[str] | None = None  # grupos actuales; None = no se sabe (se conservan)


@dataclass(frozen=True)
class DirectoryPerson:
    """Una persona del directorio del proveedor, para importarla antes de que entre (Personas → Importar).
    ``username`` es el que tendrá al iniciar sesión (las mismas reglas que el método aplica al entrar), y
    ``external_id`` el que la enlaza con esa cuenta en su primer inicio de sesión."""
    external_id: str
    username: str
    display_name: str = ""
    email: str = ""
    enabled: bool = True
    detail: str = ""                    # cargo, departamento… (solo para reconocerla en la lista)
    groups: list[str] | None = None     # sus grupos, si se saben (al importar: rol y carpetas desde ya)
    warning: str = ""                   # por qué no podría entrar aunque se importe (p. ej. sin asignar a la app)


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

    def details(self, ids) -> dict[str, dict]:
        """``{id: {"name", "description"}}`` para rellenar el alta de un grupo; por defecto, solo el nombre."""
        return {ref: {"name": name, "description": ""} for ref, name in self.names_for(ids).items()}

    def search(self, text: str, limit: int = 20) -> list[dict] | None:
        """Los grupos cuyo nombre empieza por ``text``: ``[{"id", "name"}]`` (y ``description`` si se sabe);
        ``None`` si no se puede leer el directorio."""
        return []

    def list(self, cursor: str = "", page_size: int = 50) -> tuple[list[dict], str] | None:
        """Una página de todos los grupos (como :meth:`search`) y el cursor de la siguiente (``""`` = no hay más), para
        importarlos; ``None`` si no se puede leer o no se sabe listar."""
        return None

    def clear_cache(self) -> None:
        """Olvida lo que tenga guardado en memoria (p. ej. tras restaurar una copia de seguridad)."""


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
    profile_from_provider: bool = False  # nombre y email llegan del proveedor en cada inicio de sesión: no se editan
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

    # --- SSO (opciones comunes en su configuración: auto_provision, default_role, role_mappings,
    #     sync_role_on_login y auto_login, que manda /login directamente al proveedor)
    def login_button(self, section: dict) -> LoginButton:
        return LoginButton(str(self.label))

    def begin(self, section: dict, redirect_uri: str) -> tuple[str, dict]:
        """URL del proveedor y ``flow`` (dict serializable) que se guarda en la sesión."""
        raise NotImplementedError

    def complete(self, section: dict, flow: dict, args: dict) -> Identity:
        """Valida la vuelta del proveedor. :class:`SSOError` (protocolo) o :class:`AuthDenied`."""
        raise NotImplementedError

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

    # --- revisión periódica de las cuentas contra el directorio (``core.accounts.sync_directory``)
    def sync_minutes(self, section: dict) -> int:
        """Cada cuántos minutos revisar las cuentas de este método contra su directorio (0 = nunca)."""
        return 0

    def lookup_user(self, section: dict, user) -> DirectoryUser | None:
        """Estado actual de la cuenta en el directorio; ``None`` si no se puede saber (no se toca nada)."""
        return None

    # --- importar personas del directorio antes de que entren (Personas → Importar, ``core.accounts``)
    def can_import(self, section: dict) -> bool:
        """Si se pueden buscar e importar personas de su directorio ahora (activado y con acceso a él)."""
        return False

    def search_people(self, section: dict, text: str, limit: int = 25) -> list[DirectoryPerson] | None:
        """Personas cuyo nombre, usuario o correo empieza por ``text``; ``None`` si no se puede preguntar."""
        return None

    def list_people(self, section: dict, cursor: str = "",
                    page_size: int = 50) -> tuple[list[DirectoryPerson], str] | None:
        """Todas, por páginas (*Mostrar todos*, que va cargando al bajar): ``(personas, cursor de la siguiente o
        "")``. El cursor viene del navegador: el método lo valida y nunca lo usa como dirección. ``None`` si no se
        puede preguntar."""
        return None

    def import_notice(self, section: dict) -> str:
        """Algo que no se ha podido comprobar al buscar (p. ej. un permiso que falta), o ``""``."""
        return ""

    def get_person(self, section: dict, external_id: str) -> DirectoryPerson | None:
        """Una persona por su identificador (al importar se vuelve a leer: nunca se fía de lo que manda el
        navegador), con sus grupos si se pueden leer; ``None`` si no existe o no se puede saber."""
        return None

    # --- cierre de sesión iniciado por el proveedor (canal frontal)
    def frontchannel_session(self, section: dict, args: dict) -> str | None:
        """La sesión del proveedor que se cierra (de los parámetros de la petición); ``None`` = no lo admite."""
        return None

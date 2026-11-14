"""Mapa de la administración: zonas (barra lateral) y páginas (submenú de cada zona).

Es la única fuente de la navegación: la barra lateral, el submenú, el Resumen y el buscador se
construyen a partir de :data:`ZONES`. Cada página dice de qué tipo es:

- ``config``: un formulario que se aplica al guardar;
- ``op``: acciones que se aplican al momento (cerrar sesiones, bloquear IPs, copias…);
- ``info``: solo lectura.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from flask import request, url_for

from ..i18n import _l
from ..settings import fields


@dataclass(frozen=True)
class Page:
    key: str
    label: object
    endpoint: str
    args: dict = field(default_factory=dict)
    kind: str = "config"            # config | op | info
    hint: object = ""               # una línea para el Resumen y el buscador
    also: tuple[str, ...] = ()      # otros endpoints (o prefijos «x.*») que cuentan como esta página
    words: str = ""                 # sinónimos para el buscador (en los dos idiomas)

    def url(self, **extra) -> str:
        return url_for(self.endpoint, **self.args, **extra)

    def matches(self, endpoint: str, view_args: dict) -> bool:
        if endpoint == self.endpoint and all(view_args.get(k) == v for k, v in self.args.items()):
            return True
        return any(endpoint == a or (a.endswith("*") and endpoint.startswith(a[:-1])) for a in self.also)


@dataclass(frozen=True)
class Zone:
    key: str
    label: object
    icon: str
    pages: tuple[Page, ...]
    hint: object = ""

    @property
    def first(self) -> Page:
        return self.pages[0]


def _settings(key: str, label, kind: str = "config", hint="", also: tuple[str, ...] = (), words: str = "") -> Page:
    return Page(key, label, "settings.section", {"name": key}, kind, hint, also, words)


OVERVIEW = Page("overview", _l("Overview"), "admin.index", kind="info", also=("admin.search",))

ZONES: tuple[Zone, ...] = (
    Zone("people", _l("People"), "users", (
        Page("users", _l("Users"), "admin.users_index", kind="op", hint=_l("Accounts, roles and status"),
             also=("admin.user*",), words="usuarios cuentas alta baja accounts"),
        Page("groups", _l("Groups"), "groups.index", kind="op", hint=_l("Local and Entra ID groups and their members"),
             also=("groups.list_view", "groups.panel_view", "groups.new", "groups.edit"),
             words="grupos miembros members"),
        _settings("sessions", _l("Sessions and tokens"), "op", _l("Who is signed in and which API tokens exist"),
                  words="sesiones conectados tokens api signed"),
    ), _l("Who can sign in and the groups they belong to.")),
    Zone("access", _l("Access"), "key", (
        Page("folders", _l("Shared folders"), "access.folders",
             hint=_l("Each folder, who enters and with which permission"),
             also=("access.*",), words="carpetas compartidas shares acceso permiso folders"),
        Page("matrix", _l("Access matrix"), "groups.matrix_view", hint=_l("Groups × folders in one table"),
             words="matriz accesos grupos carpetas"),
        _settings("permissions", _l("Role permissions"), hint=_l("What the «User» role can do"),
                  words="permisos rol subir descargar borrar renombrar upload delete rename"),
        _settings("storage", _l("Personal folders"), hint=_l("Where personal folders live and upload limits"),
                  words="almacenamiento home carpeta personal tamaño límite storage size limit"),
    ), _l("Who sees each folder. Groups are created in People → Groups.")),
    Zone("security", _l("Security"), "shield", (
        _settings("auth", _l("Sign-in"), hint=_l("Local users, PAM and Microsoft Entra ID"),
                  also=("settings.entra_*",), words="inicio sesión login entra microsoft pam sso secreto secret"),
        _settings("security", _l("Blocking rules"), hint=_l("Failed sign-ins, automatic IP blocking and API tokens"),
                  words="bloqueo intentos fallidos contraseña ip automático tokens lockout"),
        _settings("ips", _l("Blocked IPs"), "op", _l("Blocked addresses and the allow list"),
                  words="ip bloqueadas desbloquear ban unban lista permitidas allow"),
        Page("audit", _l("Audit"), "admin.audit_log", kind="info", hint=_l("Who did what and when"),
             also=("admin.audit_export",), words="auditoría registro eventos log"),
    ), _l("How users sign in and how the server defends itself.")),
    Zone("system", _l("System"), "settings", (
        _settings("general", _l("General and branding"), hint=_l("Name, default language, logo and color"),
                  words="nombre idioma logo color marca branding language"),
        _settings("network", _l("Network and HTTPS"), hint=_l("Public address, reverse proxy and HTTPS"),
                  words="red https proxy fqdn dominio url pública public certificate"),
        _settings("maintenance", _l("Maintenance"), hint=_l("Audit retention and automatic backups"),
                  words="mantenimiento retención copias automáticas retention"),
        _settings("backups", _l("Backups and database"), "op", _l("Create, download and delete backups"),
                  words="copias seguridad backup restaurar base datos compactar vacuum"),
        _settings("system", _l("Information"), "info", _l("Startup settings and where each value comes from"),
                  words="sistema información versión config.json system info"),
    ), _l("The server itself: name, network, maintenance and backups.")),
)

PAGES: dict[str, Page] = {p.key: p for z in ZONES for p in z.pages}
ZONE_OF: dict[str, Zone] = {p.key: z for z in ZONES for p in z.pages}
KIND_LABELS = {"config": _l("Configuration · applies when saved"), "op": _l("Operation · applies at once"),
               "info": _l("Read only")}

def page_for_path(path: str) -> str:
    """Clave de la página que edita un campo (``auth.entra.client_id`` → ``auth``)."""
    return fields.page_of(path)


def current() -> tuple[Zone | None, Page | None]:
    endpoint = request.endpoint or ""
    args = request.view_args or {}
    if OVERVIEW.matches(endpoint, args):
        return None, OVERVIEW
    for zone in ZONES:
        for page in zone.pages:
            if page.matches(endpoint, args):
                return zone, page
    return None, None


def context(modified_paths) -> dict:
    """Variables de plantilla: zona y página actuales y valores no predeterminados por página."""
    zone, page = current()
    per_page: dict[str, int] = {}
    for path in modified_paths:
        key = page_for_path(path)
        per_page[key] = per_page.get(key, 0) + 1
    return {"nav_zones": ZONES, "nav_zone": zone, "nav_page": page, "nav_overview": OVERVIEW,
            "nav_changed": per_page, "KIND_LABELS": KIND_LABELS}

"""Método de inicio de sesión «entra»: Microsoft Entra ID (SSO OAuth2/OIDC)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ...i18n import _, _l, format_datetime, ngettext
from ...settings import checks
from ...settings.auth_methods import AuthConfig
from ...settings.defaults import ROLES
from ...settings.errors import ConfigError
from ...settings.fields import Field
from ..base import (AuthDenied, AuthMethod, DirectoryPerson, DirectoryUser, GroupDirectory, Identity, LoginButton,
                    Notice)
from . import directory
from .common import MULTI_TENANT
from .oauth2 import GRANTED_KEY
from .sso import SSO_PROVIDERS, get_sso_provider

GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_log = logging.getLogger(__name__)


def _validate(section: dict, cfg: dict) -> None:
    checks.one_of(section["provider"], list(SSO_PROVIDERS), "auth.entra.provider")
    section["scopes"] = checks.str_list(section["scopes"], "auth.entra.scopes")
    section["allowed_groups"] = checks.str_list(section["allowed_groups"], "auth.entra.allowed_groups")
    if section["default_role"] and not checks.role_key(section["default_role"]):   # vacío: el de las cuentas nuevas
        checks.one_of(section["default_role"], ROLES, "auth.entra.default_role")
    section["role_mappings"] = checks.role_mappings(section["role_mappings"], "auth.entra.role_mappings")
    section["timeout_seconds"] = checks.positive_int(section["timeout_seconds"], "auth.entra.timeout_seconds")
    section["secret_expires"] = checks.iso_datetime(section.get("secret_expires"), "auth.entra.secret_expires")
    section["secret_months"] = checks.int_range(section.get("secret_months"), 1, 24, "auth.entra.secret_months")
    section["secret_warn_days"] = checks.int_range(section.get("secret_warn_days"), 1, 365, "auth.entra.secret_warn_days")
    section["auto_login"] = bool(section.get("auto_login"))
    section["directory_sync_minutes"] = checks.non_negative_int(section.get("directory_sync_minutes", 0) or 0,
                                                                "auth.entra.directory_sync_minutes")
    if section["enabled"]:
        required = ["client_id", "client_secret"]
        custom_endpoints = all(section.get(k) for k in ("authorize_url", "token_url", "issuer"))
        if section["provider"] == "msal" or not custom_endpoints:
            required.append("tenant_id")
        missing = [k for k in required if not section.get(k)]
        if missing:
            raise ConfigError(_("Entra ID is enabled but these are missing: %(fields)s", fields=", ".join(missing)),
                              f"auth.entra.{missing[0]}")


CONFIG = AuthConfig(
    key="entra",
    defaults={
        "enabled": False,
        # "oauth2": OAuth2/OIDC propio (librería estándar, sin descubrimiento previo)
        # "msal":   librería oficial de Microsoft (descubre la autoridad por red)
        "provider": "oauth2",
        "tenant_id": "",
        "client_id": "",
        "client_secret": "",
        "scopes": ["User.Read"],
        # Vacío = texto traducido por defecto ("Iniciar sesión con Microsoft")
        "button_label": "",
        "username_claim": "preferred_username",
        "strip_domain": False,
        # IDs de grupo o App Roles permitidos (vacío = cualquiera del tenant)
        "allowed_groups": [],
        # --- Alta de usuarios (opciones comunes de los métodos SSO) ---
        # True: se crea el usuario automáticamente en su primer login
        # False: solo pueden entrar usuarios dados de alta antes por un admin
        "auto_provision": True,
        # Rol asignado a los usuarios nuevos si no aplica ningún mapeo
        "default_role": "",
        # Grupo (Object ID) o App Role -> rol. Ej.: {"StorageWeb.Admin": "admin"}
        "role_mappings": {},
        # True: con role_mappings definidos, el rol se recalcula en cada login
        "sync_role_on_login": True,
        # Cada cuántos minutos se revisan contra Entra ID las cuentas con sesión o token (0 = nunca)
        "directory_sync_minutes": 60,
        "single_logout": False,
        # True: /login va directamente a Microsoft (en equipos unidos a Entra ID, sin escribir nada).
        # /login?manual=1 sigue mostrando la página para entrar con usuario y contraseña
        "auto_login": False,
        # Solo oauth2: endpoints propios (Entra soberano u otro proveedor OIDC)
        "authorize_url": "",
        "token_url": "",
        "issuer": "",
        "logout_url": "",
        "timeout_seconds": 15,
        # Caducidad del client_secret (ISO 8601); vacía = desconocida. Se avisa secret_warn_days antes.
        "secret_expires": "",
        # Meses que vale un secreto que crea StorageWeb (registrar, renovar, reparar); Microsoft admite hasta 24 y
        # las directivas del tenant pueden exigir menos
        "secret_months": 24,
        # Días antes de que caduque el secreto en que empieza el aviso del Resumen
        "secret_warn_days": 30,
    },
    fields={
        "enabled": Field(doc="Activar el inicio de sesión con Microsoft Entra ID.", label="Microsoft Entra ID",
                         page="auth", words="entra azure microsoft sso oidc oauth"),
        "provider": Field(
            doc="Implementación: `oauth2` (propia, sin descubrimiento por red) o `msal` (librería de Microsoft).",
            label=_l("Implementation"), page="auth"),
        "tenant_id": Field(doc="Directory (tenant) ID. También admite `organizations` o `common` (multi-tenant).",
                           label="Tenant ID", page="auth", words="entra tenant inquilino"),
        "client_id": Field(doc="Application (client) ID del registro de aplicación.", label="Client ID", page="auth",
                           words="entra aplicación app client"),
        "client_secret": Field(doc="Secreto del registro de aplicación. Nunca se muestra en la web.",
                               label="Client secret", page="auth", words="entra secreto secret contraseña"),
        "scopes": Field(doc="Scopes adicionales a `openid profile email`.", label=_l("Additional scopes"),
                        page="auth", form=lambda value: " ".join(map(str, value))),
        "button_label": Field(
            doc="Texto del botón de inicio de sesión. Vacío = texto por defecto en el idioma del usuario.",
            label=_l("Button text"), page="auth", words="entra botón button"),
        "username_claim": Field(doc="Claim del id_token que se usa como nombre de usuario.",
                                label=_l("User name claim"), page="auth", words="entra claim usuario"),
        "strip_domain": Field(
            doc=("Quitar el dominio del nombre de usuario (`juan@contoso.com` → `juan`). Cuidado con las colisiones "
                 "con usuarios locales."),
            label=_l("Remove the domain from the user name (juan@contoso.com → juan)"), page="auth"),
        "allowed_groups": Field(doc="Grupos (Object ID) o App Roles permitidos; vacío = cualquier usuario del tenant.",
                                label=_l("Allowed groups / App Roles"), page="auth",
                                words="entra grupos permitidos app roles"),
        "auto_provision": Field(
            doc=("Crear el usuario automáticamente en su primer inicio de sesión. Si es `false`, solo entran los "
                 "usuarios dados de alta antes por un administrador."),
            label=_l("Create the user automatically on first sign-in"), page="auth",
            words="entra alta automática provisioning"),
        "default_role": Field(doc=("Rol de los usuarios nuevos cuando no aplica ningún mapeo: `user`, `admin` o la "
                                   "clave de un rol propio; vacío = el de las cuentas nuevas de StorageWeb "
                                   "(`permissions.default_role`)."),
                              label=_l("Default role"), page="auth", words="entra rol role"),
        "role_mappings": Field(
            doc=("Grupo (Object ID) o App Role → rol, p. ej. `{\"StorageWeb.Admin\": \"admin\"}`. Si coinciden "
                 "varios, gana `admin`."),
            label=_l("Group / App Role → role mapping"), page="auth", words="entra rol mapeo administradores mapping"),
        "sync_role_on_login": Field(doc="Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión.",
                                    label=_l("Recalculate the role on every sign-in according to the mapping"),
                                    page="auth"),
        "directory_sync_minutes": Field(
            doc=("Cada cuántos minutos se revisan contra Entra ID las cuentas que pueden entrar sin pasar por "
                 "Microsoft (sesión abierta, tokens de API, unidad de red, extensión de VS Code): se desactivan las "
                 "borradas, desactivadas o fuera de los grupos permitidos (y se reactivan solas al volver), y se "
                 "actualizan sus grupos y su rol. Necesita el permiso de aplicación `User.Read.All`. `0` = solo al "
                 "iniciar sesión. La revisión corre cada 10 minutos como mucho."),
            label=_l("Check accounts against Entra ID every (minutes)"), page="auth",
            words="entra sincronizar revisar cuentas desactivadas borradas grupos tokens directorio sync"),
        "auto_login": Field(
            doc=("Ir directamente a Microsoft sin mostrar la página de inicio de sesión. En equipos unidos a Entra ID "
                 "(Intune) se entra sin escribir nada. `/login?manual=1` sigue mostrando la página (usuarios locales, "
                 "rescate)."),
            label=_l("Sign in directly with Microsoft (skip the sign-in page)"), page="auth",
            words="entra automático directo sso transparente intune skip login"),
        "single_logout": Field(doc="Cerrar también la sesión de Microsoft al salir.",
                               label=_l("Also sign out of Microsoft when signing out"), page="auth",
                               words="entra cerrar sesión logout"),
        "authorize_url": Field(
            doc="Solo `oauth2`: endpoint de autorización propio (nubes soberanas u otro proveedor OIDC).",
            label="Authorize URL", page="auth"),
        "token_url": Field(doc="Solo `oauth2`: endpoint de token propio.", label="Token URL", page="auth"),
        "issuer": Field(doc="Solo `oauth2`: valor esperado del claim `iss`.", label="Issuer", page="auth"),
        "logout_url": Field(doc="Endpoint de cierre de sesión propio.", label="Logout URL", page="auth"),
        "timeout_seconds": Field(doc="Tiempo máximo de espera al endpoint de token, en segundos.",
                                 label=_l("Timeout (s)"), page="auth"),
        "secret_expires": Field(
            doc=("Fecha de caducidad del `client_secret` (ISO 8601). La rellenan el registro automático y la "
                 "renovación; con ella se avisa a los admins `secret_warn_days` días antes."),
            label=_l("The secret expires on"), page="auth", words="entra secreto caducidad caduca expira expiry",
            form=lambda value: str(value or "")[:10]),
        "secret_months": Field(
            doc=("Meses que vale un `client_secret` que crea StorageWeb (registrar la aplicación, *Renovar el "
                 "secreto*, *Reparar*), de 1 a 24. Microsoft admite hasta 24; si las directivas del tenant piden "
                 "menos (p. ej. 6 o 12), pon ese número o Entra ID rechazará el secreto."),
            label=_l("New secrets last (months)"), page="auth",
            words="entra secreto caducidad meses duración directiva policy lifetime months"),
        "secret_warn_days": Field(
            doc="Días antes de que caduque el `client_secret` en que empieza el aviso del Resumen (de 1 a 365).",
            label=_l("Warn before the secret expires (days)"), page="auth",
            words="entra secreto aviso caduca días warn expiry"),
    },
    validate=_validate,
    secrets=("client_secret",),
    leaf=("role_mappings",),
    order=30,
)


class EntraDirectory(GroupDirectory):
    def __init__(self, section: dict):
        self.section = section

    def configured(self) -> bool:
        return directory.configured(self.section)

    def names_for(self, ids) -> dict[str, str]:
        return directory.names_for(self.section, ids)

    def details(self, ids) -> dict[str, dict]:
        return directory.info_for(self.section, ids)

    def search(self, text: str) -> list[dict]:
        return directory.search_groups(self.section, text)

    def clear_cache(self) -> None:
        directory.clear_cache()


def secret_days(section: dict) -> int | None:
    """Días hasta que caduca el secreto (negativo si ya caducó), o ``None`` si no se sabe."""
    if not section.get("secret_expires") or not section.get("client_id"):
        return None
    return (datetime.fromisoformat(section["secret_expires"]) - datetime.now(timezone.utc)).days


def granted_scopes(value) -> list[str] | None:
    """El ``scope`` de la respuesta del token («openid profile https://graph.microsoft.com/User.Read»,
    o una lista) → nombres cortos; None si el proveedor no lo dice."""
    if value is None or value == "":
        return None
    items = value.split() if isinstance(value, str) else list(value)
    return sorted({str(s).rsplit("/", 1)[-1] for s in items if s})


def groups_overage(claims: dict) -> bool:
    """Más grupos de los que caben en el token (200): Entra ID no manda ``groups`` y deja una referencia."""
    names = claims.get("_claim_names")
    return bool((isinstance(names, dict) and "groups" in names) or claims.get("hasgroups"))


# El claim del token que da el nombre de usuario (auth.entra.username_claim) → el campo de Graph que lleva lo mismo
_CLAIM_FIELDS = {"preferred_username": "userPrincipalName", "upn": "userPrincipalName", "unique_name": "userPrincipalName",
                 "email": "mail"}


def username_from(section: dict, value: str) -> str:
    """El nombre de usuario como lo da el inicio de sesión: en minúsculas y sin el dominio si ``strip_domain``."""
    raw = str(value or "").strip().lower()
    return raw.split("@")[0] if section.get("strip_domain") else raw


def person_from_graph(section: dict, user: dict) -> DirectoryPerson | None:
    """Una cuenta de Graph → :class:`DirectoryPerson`, con el nombre de usuario que le dará su primer inicio de
    sesión (el mismo claim que ``identity_from_claims``; si es uno que Graph no tiene, el UPN)."""
    field = _CLAIM_FIELDS.get(section.get("username_claim") or "preferred_username", "userPrincipalName")
    username = username_from(section, user.get(field) or user.get("userPrincipalName") or user.get("mail") or "")
    if not user.get("id") or not username:
        return None
    detail = " · ".join(str(x) for x in (user.get("jobTitle"), user.get("department")) if x)
    return DirectoryPerson(external_id=str(user["id"]).lower(), username=username,
                           display_name=str(user.get("displayName") or ""),
                           email=str(user.get("mail") or user.get("userPrincipalName") or ""),
                           enabled=bool(user.get("accountEnabled", True)), detail=detail)


NOT_ASSIGNED = _l("Not assigned to the application in Entra ID («Assignment required» is on): they cannot sign in "
                  "until an administrator assigns them, or one of their groups, in the enterprise application.")


def _with_assignment(section: dict, people: list[DirectoryPerson]) -> list[DirectoryPerson]:
    """Las personas con el aviso de las que no podrían entrar porque la aplicación exige asignación y no lo están (ni
    ellas ni un grupo del que sean miembros directos). Lo que no se sabe no se avisa."""
    info = directory.assignment(section)
    if not info or not info["required"]:
        return people
    return [p if directory.assigned(p.external_id, info) else DirectoryPerson(**{**p.__dict__,
                                                                                   "warning": str(NOT_ASSIGNED)})
            for p in people]


def identity_from_claims(section: dict, claims: dict) -> Identity:
    """Claims del id_token ya validados → :class:`Identity`. :class:`AuthDenied` si no puede entrar.

    Si la persona está en tantos grupos que no caben en el token, se leen de Microsoft Graph; si tampoco se
    puede, sus grupos quedan como «no se sabe» (``None``) y se conservan los que tenía."""
    tenant = (section.get("tenant_id") or "").lower()
    if tenant and tenant not in MULTI_TENANT and str(claims.get("tid", "")).lower() != tenant:
        raise AuthDenied(_("Your account does not belong to the allowed organization."), "tenant")
    oid = claims.get("oid") or claims.get("sub")
    raw_username = str(claims.get(section["username_claim"]) or claims.get("email") or "").strip().lower()
    if not oid or not raw_username:
        raise AuthDenied(_("The Microsoft account did not return a valid identifier."), "claims")
    username = username_from(section, raw_username)
    roles = {str(x).lower() for x in claims.get("roles") or []}
    found: set[str] | None = {str(x).lower() for x in claims.get("groups") or []}
    if groups_overage(claims):
        fetched = directory.member_groups(section, oid)
        if fetched is None:
            _log.warning("Too many groups for the token and they could not be read from Graph (User.Read.All)")
        found = set(fetched) if fetched is not None else None
    groups = sorted(found | roles) if found is not None else None
    allowed = {x.lower() for x in section["allowed_groups"]}
    if allowed and groups is None and not allowed & roles:
        raise AuthDenied(_("Your groups could not be read from Microsoft, so access cannot be checked. Contact the "
                           "administrator."), "groups_unknown")
    if allowed and groups is not None and not allowed.intersection(groups):
        raise AuthDenied(_("Your account is not allowed to access this application."), "group")
    return Identity(username=username, external_id=oid, display_name=claims.get("name"),
                    email=claims.get("email") or raw_username, groups=groups,
                    granted_scopes=granted_scopes(claims.get(GRANTED_KEY)),
                    session_id=str(claims["sid"]) if claims.get("sid") else None)


class EntraMethod(AuthMethod):
    key = "entra"
    label = "Entra ID"
    description = _l("Microsoft accounts of your organization (SSO)")
    icon = "globe"
    order = 30
    sso = True
    profile_from_provider = True
    external_groups = True
    lowercase_usernames = True
    group_hint = _l("Synchronized on each sign-in from a group or App Role.")
    group_id_help = _l("Entra ID: Object ID of the group or App Role name (the id_token must include the «groups» or «roles» claim).")
    config = CONFIG

    def login_button(self, section: dict) -> LoginButton:
        return LoginButton(section["button_label"] or _("Sign in with Microsoft"), "btn-microsoft", "microsoft")

    def begin(self, section: dict, redirect_uri: str) -> tuple[str, dict]:
        return get_sso_provider(section).begin(redirect_uri)

    def complete(self, section: dict, flow: dict, args: dict) -> Identity:
        claims = get_sso_provider(section, flow.get("provider")).complete(flow, args)
        return identity_from_claims(section, claims)

    def logout_url(self, section: dict, post_logout_redirect_uri: str) -> str:
        if not section["single_logout"]:
            return ""
        return get_sso_provider(section).logout_url(post_logout_redirect_uri)

    def notices(self, section: dict) -> list[Notice]:
        days = secret_days(section)
        if days is None or days > int(section.get("secret_warn_days") or 30):
            return []
        date = format_datetime(section["secret_expires"])
        if days < 0:
            return [Notice("danger", "secret_expired", _("The Entra ID client secret has expired"),
                           _("Since %(date)s nobody can sign in with Microsoft.", date=date), _("Renew the secret"),
                           "f-auth-entra-secret_expires")]
        return [Notice("danger" if days <= 7 else "warn", "secret_expiring",
                       ngettext("The Entra ID client secret expires in %(num)s day",
                                "The Entra ID client secret expires in %(num)s days", days),
                       _("On %(date)s; after that nobody can sign in with Microsoft.", date=date),
                       _("Renew the secret"), "f-auth-entra-secret_expires")]

    def network_notes(self, section: dict, public_url: str) -> list[tuple[str, str]]:
        if public_url:
            return []
        return [("warn", _("Without a public address, the Entra ID return address depends on the name each person "
                           "uses to reach the server, and each one must be registered in Entra ID. Set the public "
                           "address."))]

    def directory(self, section: dict) -> GroupDirectory:
        return EntraDirectory(section)

    def sync_minutes(self, section: dict) -> int:
        if not section.get("enabled") or not directory.configured(section):
            return 0
        return int(section.get("directory_sync_minutes") or 0)

    # --- importar personas (Personas → Importar de Microsoft Entra ID)
    def can_import(self, section: dict) -> bool:
        return bool(section.get("enabled")) and directory.configured(section)

    def search_people(self, section: dict, text: str, limit: int = 25) -> list[DirectoryPerson] | None:
        found = directory.search_users(section, text, limit)
        if found is None:
            return None
        people = [p for p in (person_from_graph(section, u) for u in found) if p]
        return _with_assignment(section, people)

    def list_people(self, section: dict, cursor: str = "",
                    page_size: int = 50) -> tuple[list[DirectoryPerson], str] | None:
        page = directory.list_users(section, cursor, page_size)
        if page is None:
            return None
        found, following = page
        return _with_assignment(section, [p for p in (person_from_graph(section, u) for u in found) if p]), following

    def import_notice(self, section: dict) -> str:
        if directory.assignment(section) is None:
            return _("Whether the application requires assignment (and so who can sign in) could not be checked: it "
                     "needs the Application.Read.All permission («Repair permissions» adds it).")
        return ""

    def get_person(self, section: dict, external_id: str) -> DirectoryPerson | None:
        found = directory.get_user(section, external_id)
        person = person_from_graph(section, found) if found else None
        if person is None:
            return None
        groups = directory.member_groups(section, person.external_id) if person.enabled else None
        return _with_assignment(section, [DirectoryPerson(**{**person.__dict__, "groups": groups})])[0]

    def lookup_user(self, section: dict, user) -> DirectoryUser | None:
        state = directory.user_state(section, user["external_id"] or "")
        if state is None:
            return None
        if not state["exists"]:
            return DirectoryUser(exists=False)
        if not state["enabled"]:
            return DirectoryUser(exists=True, enabled=False)
        groups = None
        if state["groups"] is not None:
            # Los App Roles no se pueden leer sin más permisos: se conservan los del último inicio de sesión
            app_roles = {g for g in (user["external_groups"] or "").split(",") if g and not GUID_RE.match(g)}
            groups = sorted(set(state["groups"]) | app_roles)
        allowed = {x.lower() for x in section["allowed_groups"]}
        return DirectoryUser(exists=True, enabled=True, groups=groups,
                             allowed=not allowed or groups is None or bool(allowed.intersection(groups)))

    def frontchannel_session(self, section: dict, args: dict) -> str | None:
        # Entra ID llama a la «URL de cierre de sesión de canal frontal» con ?sid=…&iss=… (el claim sid del token)
        return str(args.get("sid") or "")

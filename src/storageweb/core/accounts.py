"""Cuentas de usuario: autenticación, alta automática por SSO, roles y gestión por el admin.

Lo propio de cada método de inicio de sesión (comprobar la contraseña, validar la vuelta del SSO,
qué grupos trae…) está en su proveedor (``providers/<método>/``, :class:`providers.AuthMethod`);
aquí solo lo común: cuentas, roles, grupos sincronizados y las reglas del administrador.

Todas las funciones reciben la conexión SQLite como primer argumento.
"""
from __future__ import annotations

import re
from sqlite3 import Connection

from .. import providers
from ..db.repositories import audit, sessions, users
from ..i18n import _
from ..providers import AuthDenied, AuthMethod, Identity
from ..providers.local import burn_time, hash_password
from ..settings.defaults import ROLES
from . import groups as group_core
from .alerts import alert, source
from .permissions import ADMIN, USER

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}$")


class AccountError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------------- métodos de inicio de sesión

def methods() -> list[AuthMethod]:
    return providers.methods()


def method(source: str) -> AuthMethod | None:
    return providers.get(source)


def sources() -> list[str]:
    return [m.key for m in providers.methods()]


def source_labels() -> dict[str, str]:
    return {m.key: str(m.label) for m in providers.methods()}


def stores_password(source: str) -> bool:
    """Si las cuentas de ese origen tienen la contraseña en StorageWeb (se puede cambiar aquí)."""
    m = providers.get(source)
    return bool(m and m.stores_password)


def default_source() -> str:
    """Origen propuesto al dar de alta a mano: el primero que guarda la contraseña aquí."""
    return next((m.key for m in providers.methods() if m.stores_password), sources()[0])


@source("auth", order=10)
def _auth_alerts(ctx):
    """Avisos de cada método (p. ej. el secreto de Entra ID que caduca, aunque esté desactivado)."""
    auth = ctx.cfg.get("auth", {})
    return [alert(n.level, n.key, n.title, n.detail, "auth", n.action, n.anchor)
            for m in providers.methods() if m.key in auth for n in m.notices(auth[m.key])]


# --------------------------------------------------------------------------- login con contraseña

def authenticate_password(conn: Connection, cfg: dict, username: str, password: str):
    """Comprueba usuario y contraseña con el método de la cuenta o, si no existe, con los que dan de alta."""
    user = users.get_by_username(conn, username)
    identity, used = None, None
    if user is not None:
        used = providers.get(user["source"])
        if used is not None and used.password and used.enabled(cfg):
            identity = used.verify(used.section(cfg), user, username, password)
        else:
            burn_time(password)  # p. ej. una cuenta de SSO: solo entra por su proveedor
    else:
        for candidate in providers.methods():
            if candidate.password and candidate.provisions and candidate.enabled(cfg):
                identity = candidate.verify(candidate.section(cfg), None, username, password)
                if identity is not None:
                    used = candidate
                    break
        if identity is None:
            burn_time(password)
    if identity is None:
        return None
    if user is None:
        user = users.get_by_id(conn, users.create(conn, username=username, source=used.key,
                                                  role=identity.role or USER, home_path=identity.home))
    if not user["enabled"]:
        return None
    users.touch_login(conn, user["id"], **({"role": identity.role} if identity.role else {}))
    if used.external_groups:
        group_core.sync_external(conn, user["id"], used.key, identity.groups)
    return users.get_by_id(conn, user["id"])


# --------------------------------------------------------------------------- SSO

def resolve_role(section: dict, groups: list[str] | set[str], current_role: str | None = None) -> str:
    """Rol para un usuario SSO según ``role_mappings`` de su método.

    * Usuario nuevo: rol mapeado (admin gana a user) o ``default_role``.
    * Usuario existente: si ``sync_role_on_login`` y hay mapeos, se recalcula; si no, se mantiene.
    """
    mappings = section.get("role_mappings") or {}
    default = section.get("default_role", USER)
    matched = {mappings[g] for g in groups if g in mappings}
    mapped = ADMIN if ADMIN in matched else (USER if matched else None)
    if current_role is None:
        return mapped or default
    if section.get("sync_role_on_login", True) and mappings:
        return mapped or default
    return current_role


def login_sso(conn: Connection, cfg: dict, key: str, identity: Identity, ip: str | None = None):
    """Usuario de un método SSO a partir de la identidad que devuelve su proveedor (creándolo si procede).

    Opciones comunes de los métodos SSO (en ``auth.<método>``): ``auto_provision``, ``default_role``,
    ``role_mappings`` y ``sync_role_on_login``.
    """
    section = cfg["auth"][key]
    username, groups = identity.username, identity.groups
    user = users.get_by_external(conn, key, identity.external_id)
    if user is None:
        existing = users.get_by_username(conn, username)
        if existing is not None and existing["source"] == key and not existing["external_id"]:
            # Cuenta dada de alta previamente por un admin: se vincula en el primer login
            users.update(conn, existing["id"], external_id=identity.external_id)
            user = users.get_by_id(conn, existing["id"])
            audit.log(conn, "user_linked", username=username, ip=ip, detail=key)
        elif existing is not None:
            # Nunca vincular automáticamente con una cuenta de otro origen con el mismo nombre
            raise AccountError(_("An account with that name already exists. Contact the administrator."),
                               "conflict")
        elif not section.get("auto_provision", True):
            raise AccountError(_("Your account is not registered in the application. Contact the administrator."),
                               "not_provisioned")
        else:
            uid = users.create(conn, username=username, source=key, external_id=identity.external_id,
                               role=resolve_role(section, groups), display_name=identity.display_name,
                               email=identity.email)
            user = users.get_by_id(conn, uid)
            audit.log(conn, "user_provisioned", username=username, ip=ip, detail=f"{key}:{user['role']}")

    if not user["enabled"]:
        raise AccountError(_("Your account is disabled."), "disabled")

    fields = {}
    if identity.display_name:
        fields["display_name"] = identity.display_name
    role = resolve_role(section, groups, user["role"])
    if role != user["role"]:
        fields["role"] = role
        audit.log(conn, "role_changed", username=username, ip=ip, detail=f"{user['role']}->{role} ({key})")
    users.touch_login(conn, user["id"], **fields)
    group_core.sync_external(conn, user["id"], key, groups)
    return users.get_by_id(conn, user["id"])


def complete_sso(conn: Connection, cfg: dict, key: str, flow: dict, args: dict, ip: str | None = None):
    """Valida la vuelta del proveedor y entra. :class:`AccountError` si la persona no puede entrar."""
    m = providers.get(key)
    try:
        identity = m.complete(m.section(cfg), flow, args)
    except AuthDenied as exc:
        raise AccountError(exc.message, exc.code) from exc
    return login_sso(conn, cfg, key, identity, ip=ip)


# --------------------------------------------------------------------------- gestión (admin)

def _check_role(role: str) -> None:
    if role not in ROLES:
        raise AccountError(_("Invalid role: %(role)s", role=role))


def _guard_last_admin(conn: Connection, user, new_role: str, new_enabled: bool) -> None:
    losing_admin = user["role"] == ADMIN and user["enabled"] and (new_role != ADMIN or not new_enabled)
    if losing_admin and users.count_admins(conn, exclude_id=user["id"]) == 0:
        raise AccountError(_("At least one active administrator must remain."))


def create_account(conn: Connection, *, username: str, source: str, role: str = USER, password: str | None = None,
                   display_name: str | None = None, email: str | None = None,
                   groups: list[str] | None = None, home_path: str | None = None,
                   enabled: bool = True) -> int:
    username = (username or "").strip()
    m = providers.get(source)
    if m is None:
        raise AccountError(_("Invalid source: %(source)s", source=source))
    if m.lowercase_usernames:
        username = username.lower()
    if not USERNAME_RE.match(username):
        raise AccountError(_("Invalid user name (letters, digits and . _ @ + -)."))
    _check_role(role)
    if users.get_by_username(conn, username) is not None:
        raise AccountError(_("A user with that name already exists."))
    password_hash = None
    if m.stores_password:
        try:
            password_hash = hash_password(password or "")
        except ValueError as exc:
            raise AccountError(str(exc)) from exc
    uid = users.create(conn, username=username, source=source, role=role, password_hash=password_hash,
                       display_name=display_name or None, email=email or None,
                       home_path=home_path or None, enabled=enabled)
    if groups:
        _set_groups(conn, uid, groups)
    return uid


def _set_groups(conn: Connection, user_id: int, groups: list[str]) -> None:
    try:
        group_core.set_manual_groups(conn, user_id, groups)
    except group_core.GroupError as exc:
        raise AccountError(exc.message) from exc


def update_account(conn: Connection, user, actor, *, role: str, enabled: bool, display_name: str | None,
                   email: str | None, home_path: str | None, groups: list[str] | None = None,
                   password: str | None = None) -> None:
    """Edita la cuenta. ``groups`` (si se pasa) son sus grupos manuales; los sincronizados no cambian."""
    _check_role(role)
    if user["id"] == actor["id"]:
        if role != ADMIN:
            raise AccountError(_("You cannot remove the administrator role from yourself."))
        if not enabled:
            raise AccountError(_("You cannot disable your own account."))
    _guard_last_admin(conn, user, role, enabled)
    fields = {"role": role, "enabled": enabled, "display_name": display_name or None,
              "email": email or None, "home_path": home_path or None}
    if password:
        m = providers.get(user["source"])
        if m is None or not m.stores_password:
            raise AccountError(_("Only local users have a password that can be changed."))
        try:
            fields["password_hash"] = hash_password(password)
        except ValueError as exc:
            raise AccountError(str(exc)) from exc
    users.update(conn, user["id"], **fields)
    if groups is not None:
        _set_groups(conn, user["id"], groups)
    if not enabled or password:
        sessions.delete_for_user(conn, user["id"])  # fuera las sesiones abiertas


def set_role(conn: Connection, user, actor, role: str) -> None:
    """Cambia solo el rol (acciones en bloque y edición rápida)."""
    _check_role(role)
    if user["id"] == actor["id"] and role != ADMIN:
        raise AccountError(_("You cannot remove the administrator role from yourself."))
    _guard_last_admin(conn, user, role, bool(user["enabled"]))
    users.update(conn, user["id"], role=role)


def set_enabled(conn: Connection, user, actor, enabled: bool) -> None:
    """Activa o desactiva una cuenta de cualquier origen.

    Desactivar bloquea el acceso aunque la identidad siga siendo válida en Entra ID o en el
    sistema, y cierra la sesión abierta en su siguiente petición. Para bloquear a un usuario de
    SSO hay que desactivarlo: si se elimina y ``auto_provision`` está activo, se crea de nuevo.
    """
    if user["id"] == actor["id"] and not enabled:
        raise AccountError(_("You cannot disable your own account."))
    _guard_last_admin(conn, user, user["role"], enabled)
    users.update(conn, user["id"], enabled=enabled)
    if not enabled:
        sessions.delete_for_user(conn, user["id"])


def delete_account(conn: Connection, user, actor) -> None:
    if user["id"] == actor["id"]:
        raise AccountError(_("You cannot delete your own account."))
    _guard_last_admin(conn, user, USER, False)
    users.delete(conn, user["id"])

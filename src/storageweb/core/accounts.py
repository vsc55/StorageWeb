"""Cuentas de usuario: autenticación, alta automática por SSO, roles y gestión por el admin.

Lo propio de cada método de inicio de sesión (comprobar la contraseña, validar la vuelta del SSO,
qué grupos trae…) está en su proveedor (``providers/<método>/``, :class:`providers.AuthMethod`);
aquí solo lo común: cuentas, roles, grupos sincronizados y las reglas del administrador.

Todas las funciones reciben la conexión SQLite como primer argumento.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from sqlite3 import Connection

from .. import providers
from ..db.connection import now_iso
from ..db.repositories import audit, sessions, users
from ..db.repositories import settings as settings_repo
from ..i18n import _
from ..providers import AuthDenied, AuthMethod, Identity
from ..providers.local import burn_time, hash_password
from ..settings.defaults import ROLES
from . import groups as group_core
from . import maintenance
from . import shares as share_core
from . import storage
from .alerts import alert, source
from .permissions import ADMIN, USER

_log = logging.getLogger(__name__)

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


def profile_from_provider(source: str) -> bool:
    """Si el nombre y el email de las cuentas de ese origen los pone el proveedor (Entra ID): no se editan aquí."""
    m = providers.get(source)
    return bool(m and m.profile_from_provider)


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


def signin_key(method: str) -> str:
    """Dónde se guardan los permisos concedidos en el último inicio de sesión de un método SSO."""
    return f"state:signin_scopes:{method}"


def last_signin_scopes(conn: Connection, method: str) -> dict | None:
    """``{"at": iso, "scopes": [...], "source": "signin" | "consent"}`` de lo último que se sabe de los permisos de
    inicio de sesión de ese método, o None. ``consent``: los dio StorageWeb al registrar o reparar la aplicación;
    el siguiente inicio de sesión real lo sustituye por lo que concedió de verdad el proveedor."""
    return settings_repo.get(conn, signin_key(method))


def record_signin_scopes(conn: Connection, method: str, scopes: list[str], source: str = "signin",
                         claims: list[str] | None = None) -> None:
    """``claims``: los opcionales que traía el token (``sid``), para que la comprobación diga si faltan."""
    doc = {"at": now_iso(), "scopes": sorted(scopes), "source": source}
    if claims is not None:
        doc["claims"] = sorted(claims)
    settings_repo.put(conn, signin_key(method), doc)


Renamed = Callable[[str, str], None]  # (nombre anterior, nombre nuevo): lo que fuera de core depende del nombre


def rename_account(conn: Connection, cfg: dict, user, username: str, *, ip: str | None = None,
                   on_rename: Renamed | None = None):
    """Cambia el nombre de una cuenta de un proveedor (la relación es origen + identificador externo, así que el
    nombre puede cambiar: p. ej. el UPN en Entra ID). La carpeta personal se mueve o se conserva
    (:func:`storage.home_after_rename`); ``on_rename`` actualiza lo demás que use el nombre (carpetas
    compartidas). Si el nombre nuevo ya es de otra cuenta, no se cambia."""
    old = user["username"]
    other = users.get_by_username(conn, username)
    if other is not None and other["id"] != user["id"]:
        _log.warning("Account %s cannot be renamed to %s: the name is taken", old, username)
        audit.log(conn, "user_rename_failed", username=old, ip=ip, detail=f"{old} -> {username}: taken")
        return user
    fields, home = storage.home_after_rename(user, username, cfg)
    users.rename(conn, user["id"], username)
    if fields:
        users.update(conn, user["id"], **fields)
    audit.log(conn, "user_renamed", username=username, ip=ip,
              detail=f"{old} -> {username}" + (f"; home {home}" if home else ""))
    if on_rename is not None:
        on_rename(old, username)
    return users.get_by_id(conn, user["id"])


def login_sso(conn: Connection, cfg: dict, key: str, identity: Identity, ip: str | None = None,
              on_rename: Renamed | None = None):
    """Usuario de un método SSO a partir de la identidad que devuelve su proveedor (creándolo si procede).

    La cuenta se busca por origen + identificador externo: si el proveedor trae otro nombre (UPN cambiado), se
    renombra (:func:`rename_account`). Una cuenta que desactivó el directorio se reactiva al entrar (el proveedor
    la ha dejado entrar). Opciones comunes de los métodos SSO (en ``auth.<método>``): ``auto_provision``,
    ``default_role``, ``role_mappings`` y ``sync_role_on_login``.
    """
    section = cfg["auth"][key]
    username = identity.username
    groups = identity.groups or []
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

    if not user["enabled"] and user["disabled_reason"] == users.DIRECTORY:
        users.update(conn, user["id"], enabled=True, disabled_reason=None)
        audit.log(conn, "user_enabled", username=user["username"], ip=ip, detail=f"{key}:signin")
        user = users.get_by_id(conn, user["id"])
    if not user["enabled"]:
        raise AccountError(_("Your account is disabled."), "disabled")
    if username != user["username"]:
        user = rename_account(conn, cfg, user, username, ip=ip, on_rename=on_rename)
    if identity.groups is None:  # no se pudieron leer: se conservan los de antes
        groups = sorted(group_core.split(user["external_groups"]))

    fields = {}
    if identity.display_name:
        fields["display_name"] = identity.display_name
    if identity.email and profile_from_provider(key):
        fields["email"] = identity.email
    role = resolve_role(section, groups, user["role"])
    if role != user["role"]:
        fields["role"] = role
        audit.log(conn, "role_changed", username=username, ip=ip, detail=f"{user['role']}->{role} ({key})")
    users.touch_login(conn, user["id"], **fields)
    if identity.granted_scopes is not None:
        record_signin_scopes(conn, key, identity.granted_scopes, claims=["sid"] if identity.session_id else [])
    if identity.groups is not None:
        group_core.sync_external(conn, user["id"], key, groups)
        refresh_group_details(conn, cfg, key, groups)
    return users.get_by_id(conn, user["id"])


def refresh_group_details(conn: Connection, cfg: dict, key: str, refs) -> list[str]:
    """Nombre y descripción de los grupos ya dados de alta, desde el directorio del método (si tiene)."""
    m = providers.get(key)
    found = m.directory(m.section(cfg)) if m is not None else None
    if found is None or not found.configured():
        return []
    registered = {g["external_id"] for g in group_core.repo.list_all(conn, source=key) if g["external_id"]}
    wanted = sorted(registered.intersection(refs)) if refs is not None else sorted(registered)
    if not wanted:
        return []
    try:
        details = found.details(wanted)
    except Exception:  # noqa: BLE001 (leer el directorio nunca impide entrar)
        _log.exception("Group details could not be read from %s", key)
        return []
    return group_core.refresh_details(conn, key, details)


def complete_sso(conn: Connection, cfg: dict, key: str, flow: dict, args: dict, ip: str | None = None,
                 on_rename: Renamed | None = None) -> tuple:
    """Valida la vuelta del proveedor y entra: (usuario, identidad). :class:`AccountError` si no puede entrar."""
    m = providers.get(key)
    try:
        identity = m.complete(m.section(cfg), flow, args)
    except AuthDenied as exc:
        raise AccountError(exc.message, exc.code) from exc
    return login_sso(conn, cfg, key, identity, ip=ip, on_rename=on_rename), identity


# --------------------------------------------------------------------------- revisión contra el directorio

def _sync_hours(cfg: dict) -> float:
    minutes = [m.sync_minutes(cfg["auth"][m.key]) for m in providers.methods() if m.key in cfg.get("auth", {})]
    minutes = [x for x in minutes if x > 0]
    return min(minutes) / 60 if minutes else 0


def _disable_by_directory(conn: Connection, user, key: str, why: str) -> None:
    users.update(conn, user["id"], enabled=False, disabled_reason=users.DIRECTORY)
    closed = sessions.delete_for_user(conn, user["id"])
    _log.warning("Account %s disabled: %s in %s", user["username"], why, key)
    audit.log(conn, "user_disabled", user["username"], username="system", detail=f"{key}:{why}; sessions={closed}")


def sync_directory(conn: Connection, cfg: dict, only: str | None = None) -> dict:
    """Revisa contra su directorio las cuentas que pueden entrar sin pasar por el proveedor (sesión abierta,
    tokens de API, unidad de red, extensión de VS Code) y las que desactivó el directorio:

    * borrada, desactivada o fuera de los grupos permitidos → se desactiva (``disabled_reason = directory``) y se
      cierran sus sesiones; sus tokens dejan de valer mientras tanto;
    * desactivada por el directorio y otra vez válida → se reactiva;
    * grupos y rol, como en un inicio de sesión (sin tocar los App Roles, que solo llegan en el token);
    * nombre y descripción de los grupos dados de alta.

    Si el directorio no responde, no se toca nada. Devuelve un resumen por método.
    """
    summary = {}
    for m in providers.methods():
        section = cfg.get("auth", {}).get(m.key)
        if section is None or (only and m.key != only) or not m.sync_minutes(section):
            continue
        done = {"checked": 0, "disabled": 0, "enabled": 0, "updated": 0, "unknown": 0, "groups": 0}
        for user in users.directory_candidates(conn, m.key):
            found = m.lookup_user(section, user)
            done["checked"] += 1
            if found is None:
                done["unknown"] += 1
                continue
            why = ("deleted" if not found.exists else "disabled" if not found.enabled
                   else "not_allowed" if not found.allowed else "")
            if why:
                if user["enabled"]:
                    _disable_by_directory(conn, user, m.key, why)
                    done["disabled"] += 1
                continue
            if not user["enabled"]:
                users.update(conn, user["id"], enabled=True, disabled_reason=None)
                audit.log(conn, "user_enabled", user["username"], username="system", detail=f"{m.key}:directory")
                done["enabled"] += 1
            if found.groups is None:
                continue
            before = group_core.split(user["external_groups"])
            role = resolve_role(section, found.groups, user["role"])
            if set(found.groups) != before or role != user["role"]:
                group_core.sync_external(conn, user["id"], m.key, found.groups)
                if role != user["role"]:
                    users.update(conn, user["id"], role=role)
                    audit.log(conn, "role_changed", user["username"], username="system",
                              detail=f"{user['role']}->{role} ({m.key}:directory)")
                done["updated"] += 1
        done["groups"] = len(refresh_group_details(conn, cfg, m.key, None))
        summary[m.key] = done
        if done["disabled"] or done["enabled"] or done["updated"] or done["groups"]:
            audit.log(conn, "directory_synced", None, username="system",
                      detail=f"{m.key}: " + ", ".join(f"{k}={v}" for k, v in done.items()))
    return summary


@maintenance.task("directory_sync", every=_sync_hours, order=15)
def _sync_directory(conn: Connection, cfg: dict) -> None:
    sync_directory(conn, cfg)


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


KEEP = object()  # parámetro que no se cambia


def update_account(conn: Connection, user, actor, *, role: str, enabled: bool, display_name: str | None,
                   email: str | None, home_path: str | None, groups: list[str] | None = None,
                   password: str | None = None, quota_mb=KEEP) -> None:
    """Edita la cuenta. ``groups`` (si se pasa) son sus grupos manuales; los sincronizados no cambian. El nombre y
    el email de las cuentas cuyo proveedor los pone (Entra ID) no se tocan."""
    _check_role(role)
    if user["id"] == actor["id"]:
        if role != ADMIN:
            raise AccountError(_("You cannot remove the administrator role from yourself."))
        if not enabled:
            raise AccountError(_("You cannot disable your own account."))
    _guard_last_admin(conn, user, role, enabled)
    fields = {"role": role, "enabled": enabled, "home_path": home_path or None}
    if bool(enabled) != bool(user["enabled"]):
        fields["disabled_reason"] = None  # lo decide un admin: el directorio ya no la reactiva sola
    if not profile_from_provider(user["source"]):
        fields.update(display_name=display_name or None, email=email or None)
    if quota_mb is not KEEP:  # None = la de por defecto; 0 = sin cuota
        if quota_mb is not None and (not isinstance(quota_mb, int) or quota_mb < 0):
            raise AccountError(_("The quota must be a whole number of MB (0 = no quota; empty = the default one)."))
        fields["quota_mb"] = quota_mb
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
    users.update(conn, user["id"], enabled=enabled, disabled_reason=None)
    if not enabled:
        sessions.delete_for_user(conn, user["id"])


def delete_account(conn: Connection, user, actor) -> None:
    if user["id"] == actor["id"]:
        raise AccountError(_("You cannot delete your own account."))
    _guard_last_admin(conn, user, USER, False)
    users.delete(conn, user["id"])

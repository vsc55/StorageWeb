"""Cuentas de usuario: autenticación, alta automática por SSO, roles y gestión por el admin.

Todas las funciones reciben la conexión SQLite como primer argumento.
"""
from __future__ import annotations

import re
from sqlite3 import Connection

from ..db.repositories import audit, users
from ..settings.defaults import ROLES
from ..providers import local, pam
from ..providers.base import MULTI_TENANT
from .permissions import ADMIN, USER

SOURCES = ("local", "entra", "pam")
SOURCE_LABELS = {"local": "Local", "entra": "Entra ID", "pam": "Sistema (PAM)"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,127}$")


class AccountError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------------- login con contraseña

def authenticate_password(conn: Connection, cfg: dict, username: str, password: str):
    """Usuario local (SQLite) o, si no existe como local/entra, usuario del sistema (PAM)."""
    user = users.get_by_username(conn, username)

    if user is not None and user["source"] == "local":
        if not cfg["auth"]["local"]["enabled"]:
            local.burn_time(password)
            return None
        if user["enabled"] and local.verify(user["password_hash"], password):
            users.touch_login(conn, user["id"])
            return users.get_by_id(conn, user["id"])
        return None

    if user is not None and user["source"] == "entra":
        local.burn_time(password)
        return None  # las cuentas de Entra ID solo entran por SSO

    pcfg = cfg["auth"]["pam"]
    groups = pam.authenticate(pcfg, username, password)
    if groups is None:
        if user is None:
            local.burn_time(password)
        return None
    admin_groups = set(pcfg["admin_groups"])
    role = ADMIN if admin_groups.intersection(groups) else USER
    if user is None:
        home = pam.system_home(username) if pcfg["use_system_home"] else None
        user = users.get_by_id(conn, users.create(conn, username=username, source="pam", role=role,
                                            groups=groups, home_path=home))
    if not user["enabled"]:
        return None
    fields = {"groups": groups}
    if admin_groups:
        fields["role"] = role
    users.touch_login(conn, user["id"], **fields)
    return users.get_by_id(conn, user["id"])


# --------------------------------------------------------------------------- SSO

def resolve_role(ecfg: dict, groups: list[str] | set[str], current_role: str | None = None) -> str:
    """Rol para un usuario SSO según ``role_mappings``.

    * Usuario nuevo: rol mapeado (admin gana a user) o ``default_role``.
    * Usuario existente: si ``sync_role_on_login`` y hay mapeos, se recalcula; si no, se mantiene.
    """
    mappings = ecfg["role_mappings"]
    matched = {mappings[g] for g in groups if g in mappings}
    mapped = ADMIN if ADMIN in matched else (USER if matched else None)
    if current_role is None:
        return mapped or ecfg["default_role"]
    if ecfg["sync_role_on_login"] and mappings:
        return mapped or ecfg["default_role"]
    return current_role


def login_with_claims(conn: Connection, ecfg: dict, claims: dict, ip: str | None = None):
    """Devuelve el usuario correspondiente a los claims del id_token (creándolo si procede)."""
    tenant = (ecfg.get("tenant_id") or "").lower()
    if tenant and tenant not in MULTI_TENANT and str(claims.get("tid", "")).lower() != tenant:
        raise AccountError("Tu cuenta no pertenece a la organización permitida.", "tenant")

    oid = claims.get("oid") or claims.get("sub")
    raw_username = str(claims.get(ecfg["username_claim"]) or claims.get("email") or "").strip().lower()
    if not oid or not raw_username:
        raise AccountError("La cuenta de Microsoft no devolvió un identificador válido.", "claims")
    username = raw_username.split("@")[0] if ecfg["strip_domain"] else raw_username

    groups = sorted({str(x).lower() for x in claims.get("groups") or []} |
                    {str(x).lower() for x in claims.get("roles") or []})
    allowed = {x.lower() for x in ecfg["allowed_groups"]}
    if allowed and not allowed.intersection(groups):
        raise AccountError("Tu cuenta no tiene permiso para acceder a esta aplicación.", "group")

    user = users.get_by_external(conn, "entra", oid)
    if user is None:
        existing = users.get_by_username(conn, username)
        if existing is not None and existing["source"] == "entra" and not existing["external_id"]:
            # Cuenta dada de alta previamente por un admin: se vincula en el primer login
            users.update(conn, existing["id"], external_id=oid)
            user = users.get_by_id(conn, existing["id"])
            audit.log(conn, "user_linked", username=username, ip=ip, detail="entra")
        elif existing is not None:
            # Nunca vincular automáticamente con una cuenta local/PAM con el mismo nombre
            raise AccountError("Ya existe una cuenta con ese nombre. Contacta con el administrador.",
                               "conflict")
        elif not ecfg["auto_provision"]:
            raise AccountError("Tu cuenta no está dada de alta en la aplicación. "
                               "Contacta con el administrador.", "not_provisioned")
        else:
            uid = users.create(conn, username=username, source="entra", external_id=oid,
                               role=resolve_role(ecfg, groups), display_name=claims.get("name"),
                               email=claims.get("email") or raw_username, groups=groups)
            user = users.get_by_id(conn, uid)
            audit.log(conn, "user_provisioned", username=username, ip=ip, detail=f"entra:{user['role']}")

    if not user["enabled"]:
        raise AccountError("Tu cuenta está deshabilitada.", "disabled")

    fields = {"groups": groups}
    if claims.get("name"):
        fields["display_name"] = claims["name"]
    role = resolve_role(ecfg, groups, user["role"])
    if role != user["role"]:
        fields["role"] = role
        audit.log(conn, "role_changed", username=username, ip=ip, detail=f"{user['role']}->{role} (entra)")
    users.touch_login(conn, user["id"], **fields)
    return users.get_by_id(conn, user["id"])


# --------------------------------------------------------------------------- gestión (admin)

def _check_role(role: str) -> None:
    if role not in ROLES:
        raise AccountError(f"Rol no válido: {role}")


def _guard_last_admin(conn: Connection, user, new_role: str, new_enabled: bool) -> None:
    losing_admin = user["role"] == ADMIN and user["enabled"] and (new_role != ADMIN or not new_enabled)
    if losing_admin and users.count_admins(conn, exclude_id=user["id"]) == 0:
        raise AccountError("Debe quedar al menos un administrador activo.")


def create_account(conn: Connection, *, username: str, source: str, role: str = USER, password: str | None = None,
                   display_name: str | None = None, email: str | None = None,
                   groups: list[str] | None = None, home_path: str | None = None,
                   enabled: bool = True) -> int:
    username = (username or "").strip()
    if source == "entra":
        username = username.lower()
    if not USERNAME_RE.match(username):
        raise AccountError("Nombre de usuario no válido (letras, números y . _ @ + -).")
    if source not in SOURCES:
        raise AccountError(f"Origen no válido: {source}")
    _check_role(role)
    if users.get_by_username(conn, username) is not None:
        raise AccountError("Ya existe un usuario con ese nombre.")
    password_hash = None
    if source == "local":
        try:
            password_hash = local.hash_password(password or "")
        except ValueError as exc:
            raise AccountError(str(exc)) from exc
    return users.create(conn, username=username, source=source, role=role, password_hash=password_hash,
                        display_name=display_name or None, email=email or None, groups=groups,
                        home_path=home_path or None, enabled=enabled)


def update_account(conn: Connection, user, actor, *, role: str, enabled: bool, display_name: str | None,
                   email: str | None, groups: list[str], home_path: str | None,
                   password: str | None = None) -> None:
    _check_role(role)
    if user["id"] == actor["id"]:
        if role != ADMIN:
            raise AccountError("No puedes quitarte a ti mismo el rol de administrador.")
        if not enabled:
            raise AccountError("No puedes deshabilitar tu propia cuenta.")
    _guard_last_admin(conn, user, role, enabled)
    fields = {"role": role, "enabled": enabled, "display_name": display_name or None,
              "email": email or None, "groups": groups, "home_path": home_path or None}
    if password:
        if user["source"] != "local":
            raise AccountError("Solo se puede cambiar la contraseña de usuarios locales.")
        try:
            fields["password_hash"] = local.hash_password(password)
        except ValueError as exc:
            raise AccountError(str(exc)) from exc
    users.update(conn, user["id"], **fields)


def delete_account(conn: Connection, user, actor) -> None:
    if user["id"] == actor["id"]:
        raise AccountError("No puedes eliminar tu propia cuenta.")
    _guard_last_admin(conn, user, USER, False)
    users.delete(conn, user["id"])

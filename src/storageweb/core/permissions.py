"""Roles y permisos.

* ``admin``: todos los permisos sobre archivos + administración (usuarios, ajustes, auditoría).
* ``user``:  los permisos definidos en ``permissions.user`` (configurable desde la web).
"""
from __future__ import annotations

from ..i18n import _l
from ..db.repositories.users import groups_of
from ..settings.defaults import PERMISSIONS, ROLES

ADMIN = "admin"
USER = "user"
NONE = "none"       # de serie: ningún permiso (el de las cuentas nuevas, salvo que se elija otro)
ROLE_LABELS = {ADMIN: _l("Administrator"), USER: _l("User"), NONE: _l("No permissions")}
PERMISSION_LABELS = {
    "upload": _l("Upload files"),
    "download": _l("Download"),
    "mkdir": _l("Create folders"),
    "rename": _l("Rename"),
    "delete": _l("Delete"),
    "edit": _l("Edit text files"),
    "share": _l("Share with links"),
}
assert set(ROLE_LABELS) == set(ROLES) and set(PERMISSION_LABELS) == set(PERMISSIONS)


def is_admin(user) -> bool:
    return user is not None and user["role"] == ADMIN


def role_permissions(cfg: dict, key: str) -> frozenset[str]:
    """Los permisos de un rol: ``admin``, todos; un rol propio (``cfg["roles"]``, core/roles.py), los suyos;
    ``user`` (y uno que ya no existe), los del ajuste ``permissions.user``."""
    if key == ADMIN:
        return frozenset(PERMISSIONS)
    if key == NONE:
        return frozenset()
    custom = (cfg.get("roles") or {}).get(key)
    if custom is not None:
        return frozenset(p for p in custom["permissions"] if p in PERMISSIONS)
    granted = cfg["permissions"]["user"]
    return frozenset(p for p in PERMISSIONS if granted.get(p))


def roles_of(user, cfg: dict) -> list[str]:
    """Los roles de una persona: el suyo y los que le dan sus grupos (``cfg["group_roles"]``), sin repetir."""
    found = [user["role"]]
    group_roles = cfg.get("group_roles") or {}
    for name in sorted(groups_of(user)):
        role = group_roles.get(name.lower())
        if role and role != ADMIN and role not in found:     # un grupo nunca hace administrador
            found.append(role)
    return found


def permissions_for(user, cfg: dict) -> frozenset[str]:
    """Lo que puede hacer con los archivos: todo si es administrador; si no, lo de su rol más lo de los roles de sus
    grupos."""
    if user is None:
        return frozenset()
    if is_admin(user):
        return frozenset(PERMISSIONS)
    found: set[str] = set()
    for key in roles_of(user, cfg):
        found |= role_permissions(cfg, key)
    return frozenset(found)


def default_role(cfg: dict) -> str:
    """El rol de las cuentas nuevas (``permissions.default_role``, Acceso → Roles): de serie, Sin permisos (lo
    que puedan hacer se lo dan sus grupos o se les cambia el rol)."""
    return (cfg.get("permissions") or {}).get("default_role") or NONE


def role_label(cfg: dict, key: str) -> str:
    """El nombre de un rol para enseñarlo: los de serie, traducidos; los propios, el suyo; uno que ya no existe,
    su clave."""
    if key in ROLE_LABELS:
        return str(ROLE_LABELS[key])
    custom = (cfg.get("roles") or {}).get(key)
    return custom["label"] if custom else str(key)


def effective_for_root(perms: frozenset[str], root: dict) -> frozenset[str]:
    """En una carpeta de solo lectura únicamente se conservan 'download' y 'share' (un enlace para descargar)."""
    return perms & {"download", "share"} if root.get("read_only") else perms

"""Roles y permisos.

* ``admin``: todos los permisos sobre archivos + administración (usuarios, ajustes, auditoría).
* ``user``:  los permisos definidos en ``permissions.user`` (configurable desde la web).
"""
from __future__ import annotations

from ..i18n import _l
from ..settings.defaults import PERMISSIONS, ROLES

ADMIN = "admin"
USER = "user"
ROLE_LABELS = {ADMIN: _l("Administrator"), USER: _l("User")}
PERMISSION_LABELS = {
    "upload": _l("Upload files"),
    "download": _l("Download"),
    "mkdir": _l("Create folders"),
    "rename": _l("Rename"),
    "delete": _l("Delete"),
}
assert set(ROLE_LABELS) == set(ROLES) and set(PERMISSION_LABELS) == set(PERMISSIONS)


def is_admin(user) -> bool:
    return user is not None and user["role"] == ADMIN


def permissions_for(user, cfg: dict) -> frozenset[str]:
    if user is None:
        return frozenset()
    if is_admin(user):
        return frozenset(PERMISSIONS)
    granted = cfg["permissions"]["user"]
    return frozenset(p for p in PERMISSIONS if granted.get(p))


def effective_for_root(perms: frozenset[str], root: dict) -> frozenset[str]:
    """En una carpeta de solo lectura únicamente se conserva 'download'."""
    return perms & {"download"} if root.get("read_only") else perms

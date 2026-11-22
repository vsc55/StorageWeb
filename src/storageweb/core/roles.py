"""Roles: qué puede hacer cada persona con los archivos.

* **De serie**: ``admin`` (todo, también la administración), ``user`` (los permisos del ajuste
  ``permissions.user``, que se editan en su ficha como los demás) y ``none`` (ninguno: el de las cuentas nuevas
  de serie). No se borran ni cambian de nombre.
* **Propios** (tabla ``roles``, migración 007): un nombre y un conjunto de permisos de ``PERMISSIONS`` (subir,
  descargar, crear carpetas, renombrar, eliminar, editar textos, compartir con enlaces).

Se asignan a una **persona** (``users.role``: el suyo, uno solo) y a un **grupo** (``groups.role``: lo reciben sus
miembros, sumado al suyo). Los permisos de una persona son la suma de los de todos sus roles
(``core.permissions.permissions_for``). Un grupo nunca da ``admin``: eso lo da el rol de la persona o el mapeo de roles
de un método de inicio de sesión (Entra ID).

Los roles van en los ajustes efectivos (``roles``, ``group_roles``) para calcular los permisos sin ir a la base de
datos: cada cambio llama a ``settings.store.roles_changed`` y se vuelven a leer. Sin Flask.
"""
from __future__ import annotations

import re
from sqlite3 import Connection

from ..db.repositories import roles as repo
from ..i18n import _
from ..settings import store
from ..settings.defaults import PERMISSIONS
from ..text import slug
from . import named
from .permissions import ADMIN, NONE, ROLE_LABELS, USER, role_permissions
from ..settings.errors import UserError

BUILTIN = (ADMIN, USER, NONE)
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
RESERVED = {"new", "list", "panel"}      # rutas de web/views/roles.py: /admin/access/roles/<clave>
LABEL_MAX = 80


class RoleError(UserError):
    pass


def all_roles(conn: Connection, cfg: dict) -> list[dict]:
    """Los de serie y los propios, con sus permisos y cuántas personas y grupos los tienen."""
    counts = repo.counts(conn)
    out = []
    for key in BUILTIN:
        out.append({"key": key, "label": str(ROLE_LABELS[key]), "description": "", "builtin": True,
                    "permissions": sorted(role_permissions(cfg, key), key=PERMISSIONS.index),
                    **counts.get(key, {"users": 0, "groups": 0})})
    for role in repo.list_all(conn):
        out.append({**role, "builtin": False, **counts.get(role["key"], {"users": 0, "groups": 0})})
    return out


def choices(cfg: dict, admin: bool = True) -> list[tuple[str, str]]:
    """``(clave, nombre)`` para un desplegable: los de serie (sin ``admin`` ni ``none`` si ``admin=False``: los
    grupos, a los que «sin permisos» no les daría nada) y los propios, por nombre."""
    found = [(k, str(ROLE_LABELS[k])) for k in BUILTIN if admin or k not in (ADMIN, NONE)]
    custom = sorted(((k, v["label"]) for k, v in (cfg.get("roles") or {}).items()), key=lambda item: item[1].lower())
    return found + custom


def label_of(cfg: dict, key: str) -> str:
    from .permissions import role_label  # noqa: PLC0415
    return role_label(cfg, key)


def exists(conn: Connection, key: str) -> bool:
    return key in BUILTIN or repo.get(conn, key) is not None


def get(conn: Connection, key: str) -> dict | None:
    return repo.get(conn, key)


def _clean(label: str, description: str, permissions) -> tuple[str, str, list[str]]:
    label = " ".join(str(label or "").split())[:LABEL_MAX]
    if not label:
        raise RoleError(_("Write a name for the role."))
    wanted = {str(p) for p in permissions or ()}
    unknown = wanted - set(PERMISSIONS)
    if unknown:
        raise RoleError(_("Unknown permission: %(name)s", name=", ".join(sorted(unknown))))
    return label, str(description or "").strip()[:300], [p for p in PERMISSIONS if p in wanted]


def create(conn: Connection, label: str, description: str = "", permissions=(), key: str = "",
           username: str | None = None) -> str:
    """Crea un rol propio y devuelve su clave (la que se da o una sacada del nombre: «Diseño» → ``diseno``)."""
    label, description, permissions = _clean(label, description, permissions)
    key = str(key or "").strip().lower() or _free_key(conn, label)
    if not KEY_RE.match(key):
        raise RoleError(_("The key of a role: lower case letters, digits, - and _ (up to 40)."))
    if key in BUILTIN or key in RESERVED or repo.get(conn, key) is not None:
        raise RoleError(_("A role with the key «%(key)s» already exists.", key=key))
    if any(r["label"].lower() == label.lower() for r in repo.list_all(conn)) or \
            label.lower() in {str(v).lower() for v in ROLE_LABELS.values()}:
        raise RoleError(_("A role called «%(name)s» already exists.", name=label))
    repo.create(conn, key, label, description, permissions)
    store.roles_changed(conn, username)
    return key


def copy_of(conn: Connection, cfg: dict, key: str) -> dict | None:
    """Lo que propone *Clonar* para un rol nuevo: «X (copia)» (o «X (copia 2)»… si ya hay uno con ese nombre), su
    descripción y sus permisos. ``None`` si no existe o es Administrador (una copia no puede dar la administración)."""
    if key == ADMIN:
        return None
    if key in BUILTIN:
        label, description = str(ROLE_LABELS[key]), ""
        permissions = [p for p in PERMISSIONS if p in role_permissions(cfg, key)]
    else:
        role = repo.get(conn, key)
        if role is None:
            return None
        label, description, permissions = role["label"], role["description"] or "", list(role["permissions"])
    taken = [r["label"] for r in repo.list_all(conn)] + [str(v) for v in ROLE_LABELS.values()]
    return {"label": named.copy_label(label, taken, LABEL_MAX), "description": description,
            "permissions": permissions, "source": label}


def _free_key(conn: Connection, label: str) -> str:
    """La clave sacada del nombre («Diseño» → ``diseno``) y, si ya existe o es una ruta, con ``-2``, ``-3``… (dentro
    de los 40 caracteres): dos nombres que dan la misma clave no chocan."""
    base = slug(label, 40) or "role"
    if base in RESERVED:
        base += "-role"
    candidate, num = base, 2
    while candidate in BUILTIN or candidate in RESERVED or repo.get(conn, candidate) is not None:
        suffix = f"-{num}"
        candidate = base[:40 - len(suffix)].rstrip("-_") + suffix
        num += 1
    return candidate


def update(conn: Connection, key: str, label: str, description: str = "", permissions=(),
           username: str | None = None) -> None:
    if key in BUILTIN:
        raise RoleError(_("The built-in roles cannot be changed here."))
    if repo.get(conn, key) is None:
        raise RoleError(_("That role does not exist."))
    label, description, permissions = _clean(label, description, permissions)
    if any(r["label"].lower() == label.lower() and r["key"] != key for r in repo.list_all(conn)):
        raise RoleError(_("A role called «%(name)s» already exists.", name=label))
    repo.update(conn, key, label, description, permissions)
    store.roles_changed(conn, username)


def delete(conn: Connection, key: str, username: str | None = None) -> dict:
    """Borra un rol propio: sus personas pasan a ``none`` (sin permisos: nunca ganan permisos por borrar un rol) y
    sus grupos dejan de dar rol. Devuelve cuántas y cuántos (``{"users": n, "groups": n}``)."""
    if key in BUILTIN:
        raise RoleError(_("The built-in roles cannot be deleted."))
    if repo.get(conn, key) is None:
        raise RoleError(_("That role does not exist."))
    moved = {"users": repo.move_users(conn, key, NONE), "groups": repo.clear_groups(conn, key)}
    repo.delete(conn, key)
    store.roles_changed(conn, username)
    return moved


def usage(conn: Connection, key: str) -> dict:
    return repo.usage(conn, key)

"""Ajustes web guardados por campo: una fila por perfil y campo (tabla ``settings_values``).

Un **campo** es lo mismo que en ``fields.py`` y en los bloqueos: cada valor de una hoja del árbol de ajustes,
salvo las listas (``storage.shares``) y los diccionarios de ``LEAF_PATHS`` (``role_mappings``), que son un único
campo, como cuando se fijan en config.json. Se guarda solo la diferencia mínima con los predeterminados.

Un **perfil** (``settings_profile`` en config.json, ``default`` si no) es un juego de ajustes completo: varias
instancias pueden compartir base de datos con perfiles distintos, como si cada una tuviera su config.json.

Escribir un documento (:func:`put_doc`) solo toca las filas que cambian: cada campo conserva quién y cuándo lo
cambió, y dos guardados de cosas distintas no se pisan.
"""
from __future__ import annotations

import json
from sqlite3 import Connection

from ..db.repositories import catalog
from ..db.repositories import roles as roles_repo
from ..db.repositories import settings as state_repo
from ..db.repositories import settings_values as repo
from .defaults import LEAF_PATHS
from .layers import _set

DEFAULT_PROFILE = "default"
_MISSING = object()


# --------------------------------------------------------------------------- árbol ↔ campos

def flatten(tree: dict, path: tuple = ()) -> dict:
    """``{"auth.entra.tenant_id": valor, "storage.shares": [...]}`` a partir del árbol de ajustes."""
    out = {}
    for key, value in tree.items():
        here = path + (key,)
        if isinstance(value, dict) and here not in LEAF_PATHS:
            out.update(flatten(value, here))  # un diccionario vacío no aporta ningún campo
        else:
            out[".".join(here)] = value
    return out


def unflatten(flat: dict) -> dict:
    tree: dict = {}
    for path in sorted(flat):
        _set(tree, tuple(path.split(".")), flat[path])
    return tree


def _has_secret(value) -> bool:
    return "enc:v1:" in json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------- lectura y escritura

def read_doc(conn: Connection, profile: str = DEFAULT_PROFILE) -> dict:
    """Los ajustes guardados del perfil como árbol (los secretos, tal cual: cifrados)."""
    return unflatten(repo.values(conn, profile))


def put_doc(conn: Connection, profile: str, doc: dict, username: str | None, *, commit: bool = True) -> int:
    """Deja el perfil con exactamente los campos de ``doc``: escribe los que cambian, borra los que faltan y no
    toca los demás (conservan quién y cuándo los cambió). Devuelve cuántos campos han cambiado."""
    current = repo.values(conn, profile)
    target = flatten(doc)
    changed = 0
    for path, value in target.items():
        if current.get(path, _MISSING) != value:
            repo.upsert(conn, profile, path, value, secret=_has_secret(value), username=username)
            changed += 1
    for path in current.keys() - target.keys():
        repo.delete(conn, profile, path)
        changed += 1
    if changed:
        repo.bump(conn, profile, username)
    if commit:
        conn.commit()
    return changed


def revision(conn: Connection, profile: str = DEFAULT_PROFILE) -> int:
    return repo.revision(conn, profile)


def info(conn: Connection, profile: str = DEFAULT_PROFILE):
    return repo.info(conn, profile)


def changes(conn: Connection, profile: str = DEFAULT_PROFILE) -> dict[str, dict]:
    """Quién y cuándo cambió cada campo guardado: ``{ruta: {"by", "at"}}``."""
    return {row["path"]: {"by": row["updated_by"], "at": row["updated_at"]} for row in repo.rows(conn, profile)}


def profiles(conn: Connection) -> list:
    return repo.profiles(conn)


def profile_names(conn: Connection) -> list[str]:
    return [row["name"] for row in repo.profiles(conn)]


# --------------------------------------------------------------------------- roles propios

# Tampoco son ajustes (tabla ``roles`` y ``groups.role``), pero los permisos se calculan con los ajustes efectivos
# (``core.permissions.permissions_for``): van en ellos como ``roles`` y ``group_roles``, y cambiarlos sube esta
# revisión, que ``RuntimeSettings.current`` mira junto a la de los ajustes
ROLES_STATE = "state:roles"


def read_roles(conn: Connection) -> dict:
    """``{"roles": {clave: {"label", "permissions"}}, "group_roles": {grupo: clave}}``."""
    return {"roles": {r["key"]: {"label": r["label"], "permissions": r["permissions"]} for r in roles_repo.list_all(conn)},
            "group_roles": roles_repo.group_roles(conn)}


def roles_revision(conn: Connection) -> int:
    return state_repo.revision(conn, ROLES_STATE)


def roles_changed(conn: Connection, username: str | None = None) -> None:
    """Tras cambiar un rol o el rol de un grupo: los ajustes efectivos se vuelven a leer."""
    state_repo.put(conn, ROLES_STATE, {}, username)


# --------------------------------------------------------------------------- carpetas, ubicaciones y cuotas de grupo

# No son ajustes sino entidades con su propia tabla (``db.repositories.catalog``). Las de
# config.json o del entorno no se guardan: se leen de allí y se ven de solo lectura junto a estas.
ENTITY_PATHS = ("storage.shares", "storage.locations", "storage.group_quotas")
_SHARES, _LOCATIONS, _QUOTAS = "shares", "locations", "group_quotas"


def read_entities(conn: Connection, profile: str = DEFAULT_PROFILE) -> dict:
    """``{"shares": [...], "locations": [...], "group_quotas": {...}}`` guardadas desde la web (los secretos de
    las ubicaciones, tal cual: cifrados)."""
    return {_SHARES: catalog.list_shares(conn, profile), _LOCATIONS: catalog.list_locations(conn, profile),
            _QUOTAS: catalog.group_quotas(conn)}


def _plain(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "origin"}


def apply_entities(conn: Connection, profile: str, current: dict, target: dict, username: str | None,
                   encode=None) -> bool:
    """Deja las entidades del perfil como ``target`` escribiendo solo lo que cambia (por nombre). Sin ``commit``.
    ``encode(clave, elemento)`` prepara lo que se escribe (p. ej. cifrar los secretos de una ubicación); se compara
    sin él. Devuelve si ha cambiado algo. :class:`ConfigError` si una cuota es de un grupo que no existe."""
    from ..i18n import _  # noqa: PLC0415
    from .errors import ConfigError  # noqa: PLC0415
    changed = False
    for key, save, move, delete in ((_SHARES, catalog.save_share, catalog.move_share, catalog.delete_share),
                                    (_LOCATIONS, catalog.save_location, catalog.move_location,
                                     catalog.delete_location)):
        if key not in target:
            continue
        before = {item["name"]: (i, _plain(item)) for i, item in enumerate(current.get(key, []))}
        after = {item["name"]: (i, _plain(item)) for i, item in enumerate(target[key])}
        for name in before.keys() - after.keys():
            delete(conn, profile, name)
            changed = True
        for name, (position, item) in after.items():
            if name not in before or before[name][1] != item:
                save(conn, profile, encode(key, item) if encode else item, position, username)
                changed = True
            elif before[name][0] != position:
                move(conn, profile, name, position)
                changed = True
    if _QUOTAS in target:
        before, after = current.get(_QUOTAS, {}), target[_QUOTAS]
        for name in before.keys() | after.keys():
            if before.get(name) != after.get(name):
                if not catalog.set_group_quota(conn, name, after.get(name)):
                    raise ConfigError(_("The group %(name)s does not exist.", name=repr(name)), "storage.group_quotas")
                changed = True
        if before != after:
            catalog.bump_all(conn, username)
    if changed:
        repo.bump(conn, profile, username)
    return changed


__all__ = ["DEFAULT_PROFILE", "ENTITY_PATHS", "apply_entities", "changes", "flatten", "info", "profile_names",
           "profiles", "put_doc", "read_doc", "read_entities", "revision", "unflatten"]

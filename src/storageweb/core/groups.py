"""Grupos: alta y edición, pertenencias manuales y sincronizadas, y acceso a carpetas compartidas.

Modelo:

* Un grupo tiene un ``name`` (lo que usan las carpetas compartidas), un ``label`` visible y un
  origen: ``local`` (miembros a mano) o un método de inicio de sesión que trae grupos
  (``AuthMethod.external_groups``: Entra ID con Object ID o App Role, PAM con el grupo del sistema…).
* Las pertenencias son ``manual`` (las pone un admin) o ``sync`` (llegan al iniciar sesión). Al
  sincronizar solo se reemplazan las ``sync``.
* El grupo de serie ``admins`` (``builtin``) no se borra ni se edita: sus miembros son los usuarios
  con rol admin. Añadir o quitar a alguien cambia su rol; el control de acceso lo añade en tiempo de
  ejecución (``storage.available_roots``) para que nunca se desincronice del rol.
* ``users.groups`` es la lista efectiva: ``users.external_groups`` (lo que dice el proveedor, para
  que sigan funcionando las carpetas que referencian Object IDs) más los nombres de sus grupos.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from sqlite3 import Connection
from typing import Iterable

from .. import providers
from ..db.repositories import groups as repo
from ..db.repositories import users
from ..i18n import _, _l
from .permissions import ADMIN, USER

LOCAL = "local"  # grupos con miembros puestos a mano


def external_sources() -> list[str]:
    """Métodos de inicio de sesión que traen grupos (sus grupos se sincronizan en cada inicio de sesión)."""
    return [m.key for m in providers.methods() if m.external_groups]


def group_sources() -> list[str]:
    return [LOCAL, *external_sources()]


def group_source_labels() -> dict[str, str]:
    return {LOCAL: str(_l("Local")), **{m.key: str(m.label) for m in providers.methods() if m.external_groups}}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{0,127}$")
ACCESS_LEVELS = ("none", "read", "write")
ADMINS_GROUP = "admins"


class GroupError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def label(group) -> str:
    """Nombre visible; el del grupo de serie se traduce."""
    return _("Administrators") if group["builtin"] else group["label"]


def description(group) -> str:
    if group["builtin"]:
        return _("Users with the administrator role. Adding or removing members changes their role.")
    return group["description"]


def members(conn: Connection, group) -> list:
    return repo.admins(conn) if group["builtin"] else repo.members(conn, group["id"])


def memberships(conn: Connection, user) -> list[dict]:
    """Grupos del usuario con el origen de cada pertenencia (``manual``, ``sync`` o ``role``)."""
    rows = [dict(r) for r in repo.memberships(conn, user["id"])]
    if user["role"] == ADMIN:
        admins = repo.get_builtin(conn, ADMINS_GROUP)
        if admins is not None:
            rows.insert(0, {**dict(admins), "origin": "role"})
    return rows


def _guard_admin_removal(conn: Connection, user, actor) -> None:
    if actor is not None and user["id"] == actor["id"]:
        raise GroupError(_("You cannot remove the administrator role from yourself."))
    if user["enabled"] and users.count_admins(conn, exclude_id=user["id"]) == 0:
        raise GroupError(_("At least one active administrator must remain."))


def split(value: str | None) -> set[str]:
    return {x for x in (value or "").split(",") if x}


def _clean(values: Iterable[str]) -> list[str]:
    return sorted({str(v).strip().lower() for v in values or [] if str(v).strip()})


# --------------------------------------------------------------------------- lista efectiva

def refresh_user(conn: Connection, user_id: int) -> None:
    """Recalcula ``users.groups`` = grupos del proveedor + nombres de sus grupos."""
    user = users.get_by_id(conn, user_id)
    if user is None:
        return
    effective = split(user["external_groups"]) | repo.member_names(conn, user_id)
    users.update(conn, user_id, groups=sorted(effective))


def sync_user(conn: Connection, user) -> None:
    """Ajusta las pertenencias ``sync`` según ``external_groups`` y recalcula la lista efectiva."""
    if user["source"] in external_sources():
        external = split(user["external_groups"])
        ids = [g["id"] for g in repo.list_all(conn, source=user["source"])
               if g["external_id"] and g["external_id"] in external]
        repo.replace_sync(conn, user["id"], user["source"], ids)
    refresh_user(conn, user["id"])


def sync_external(conn: Connection, user_id: int, source: str, external: Iterable[str]) -> None:
    """Guarda los grupos que da el proveedor al iniciar sesión y sincroniza las pertenencias."""
    users.update(conn, user_id, external_groups=_clean(external))
    user = users.get_by_id(conn, user_id)
    if user["source"] == source:
        sync_user(conn, user)


def _resync(conn: Connection, user_ids: Iterable[int], source: str | None) -> None:
    ids = set(user_ids)
    if source in external_sources():
        ids |= {u["id"] for u in users.list_all(conn) if u["source"] == source}
    for uid in sorted(ids):
        user = users.get_by_id(conn, uid)
        if user is not None:
            sync_user(conn, user)


# --------------------------------------------------------------------------- gestión

def _validate(conn: Connection, *, label: str, source: str, external_id: str | None,
              group_id: int | None = None) -> str | None:
    if not label:
        raise GroupError(_("The display name is required."))
    if source not in group_sources():
        raise GroupError(_("Invalid source: %(source)s", source=source))
    external_id = (external_id or "").strip().lower() or None
    if source != LOCAL and not external_id:
        raise GroupError(_("Groups from %(source)s need the identifier of the external group.",
                           source=group_source_labels()[source]))
    if source == LOCAL:
        external_id = None
    if external_id:
        other = repo.get_by_external(conn, source, external_id)
        if other is not None and other["id"] != group_id:
            raise GroupError(_("The group «%(name)s» is already linked to that identifier.", name=other["label"]))
    return external_id


def create_group(conn: Connection, *, name: str, label: str = "", description: str = "",
                 source: str = LOCAL, external_id: str | None = None) -> int:
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        raise GroupError(_("Invalid group identifier (lowercase letters, digits and . _ @ + -)."))
    if repo.get_by_name(conn, name) is not None:
        raise GroupError(_("A group with that identifier already exists."))
    label = (label or "").strip() or name
    external_id = _validate(conn, label=label, source=source, external_id=external_id)
    gid = repo.create(conn, name=name, label=label, description=(description or "").strip(), source=source,
                      external_id=external_id)
    _resync(conn, [], source)
    return gid


def update_group(conn: Connection, group, *, label: str, description: str, source: str,
                 external_id: str | None) -> None:
    if group["builtin"]:
        raise GroupError(_("This group comes with StorageWeb and cannot be changed."))
    label = (label or "").strip()
    external_id = _validate(conn, label=label, source=source, external_id=external_id, group_id=group["id"])
    before = repo.member_ids(conn, group["id"])
    repo.update(conn, group["id"], label=label, description=(description or "").strip(), source=source,
                external_id=external_id)
    if source != group["source"] or external_id != group["external_id"]:
        # Las pertenencias sincronizadas del origen anterior ya no valen
        conn.execute("DELETE FROM user_groups WHERE group_id = ? AND origin = 'sync'", (group["id"],))
        conn.commit()
        _resync(conn, before, source)


def delete_group(conn: Connection, group) -> None:
    if group["builtin"]:
        raise GroupError(_("This group comes with StorageWeb and cannot be deleted."))
    affected = repo.member_ids(conn, group["id"])
    repo.delete(conn, group["id"])
    for uid in affected:
        refresh_user(conn, uid)


def add_member(conn: Connection, group, user) -> None:
    if group["builtin"]:
        users.update(conn, user["id"], role=ADMIN)
        return
    repo.add_member(conn, user["id"], group["id"], "manual")
    refresh_user(conn, user["id"])


def remove_member(conn: Connection, group, user, actor=None) -> None:
    if group["builtin"]:
        if user["role"] == ADMIN:
            _guard_admin_removal(conn, user, actor)
            users.update(conn, user["id"], role=USER)
        return
    membership = repo.get_membership(conn, user["id"], group["id"])
    if membership is None:
        return
    if membership["origin"] != "manual":
        raise GroupError(_("This membership comes from %(source)s and is changed there.",
                           source=group_source_labels().get(group["source"], group["source"])))
    repo.remove_member(conn, user["id"], group["id"])
    sync_user(conn, users.get_by_id(conn, user["id"]))  # si también le corresponde por el proveedor, vuelve como 'sync'


def set_manual_groups(conn: Connection, user_id: int, names: Iterable[str], create_missing: bool = True) -> None:
    """Deja como pertenencias manuales exactamente ``names`` (crea los grupos locales que falten)."""
    wanted = []
    for name in _clean(names):
        group = repo.get_by_name(conn, name)
        if group is not None and group["builtin"]:
            raise GroupError(_("The group %(name)s is given by the administrator role; change the role instead.",
                               name=repr(name)))
        if group is None:
            if not create_missing:
                raise GroupError(_("The group %(name)s does not exist.", name=repr(name)))
            group = repo.get_by_id(conn, create_group(conn, name=name))
        wanted.append(group["id"])
    for row in repo.memberships(conn, user_id):
        if row["origin"] == "manual" and row["id"] not in wanted and not row["builtin"]:
            repo.remove_member(conn, user_id, row["id"])
    for gid in wanted:
        repo.add_member(conn, user_id, gid, "manual")
    sync_user(conn, users.get_by_id(conn, user_id))


# --------------------------------------------------------------------------- grupos sin dar de alta

def detected(conn: Connection, shares: list[dict]) -> list[dict]:
    """Grupos que llegan del proveedor o que usan las carpetas pero no están dados de alta."""
    registered = repo.list_all(conn)
    names = {g["name"] for g in registered}
    externals = {(g["source"], g["external_id"]) for g in registered if g["external_id"]}
    known_ids = {g["external_id"] for g in registered if g["external_id"]}
    external = external_sources()
    found: dict[str, dict] = {}
    for user in users.list_all(conn):
        if user["source"] not in external:
            continue
        for ext in split(user["external_groups"]):
            if (user["source"], ext) in externals or ext in names:
                continue
            item = found.setdefault(ext, {"id": ext, "source": user["source"], "users": 0, "shares": []})
            item["users"] += 1
    for share in shares:
        for ref in share["groups"]:
            if ref in names or ref in known_ids:
                continue
            item = found.setdefault(ref, {"id": ref, "source": None, "users": 0, "shares": []})
            item["shares"].append(share["label"])
    return sorted(found.values(), key=lambda d: (-d["users"], d["id"]))


def refresh_details(conn: Connection, source: str, details: dict[str, dict]) -> list[str]:
    """Pone a los grupos ya dados de alta de ``source`` el nombre y la descripción de su directorio (``details``:
    ``{id externo: {"name", "description"}}``). Devuelve los identificadores de los que han cambiado."""
    changed = []
    for group in repo.list_all(conn, source=source):
        info = details.get(group["external_id"] or "")
        if not info or group["builtin"]:
            continue
        label = (info.get("name") or "").strip()[:200] or group["label"]
        description = (info.get("description") or "").strip()[:500]
        if (label, description) != (group["label"], group["description"] or ""):
            repo.update(conn, group["id"], label=label, description=description)
            changed.append(group["name"])
    return changed


def suggest_name(conn: Connection, *candidates: str | None) -> str:
    """Identificador libre a partir del primer texto que sirva: «Permitir Instalación» → ``permitir-instalacion``
    (sin tildes, en minúsculas, lo demás como guiones); si ya existe, ``-2``, ``-3``…"""
    base = ""
    for text in candidates:
        plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
        base = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9._@+-]+", "-", plain)).strip("-._@+")[:120].rstrip("-._@+")
        if base:
            break
    base = base or "group"
    name, n = base, 1
    while repo.get_by_name(conn, name) is not None:
        n += 1
        name = f"{base}-{n}"
    return name


def register_external(conn: Connection, *, source: str, external_id: str, info: dict | None = None) -> int:
    """Da de alta un grupo que llega del proveedor con lo que diga su directorio (``info``: ``name`` y
    ``description``); sin directorio, con el identificador externo como nombre. Si ya estaba dado de alta, le
    actualiza esos datos y devuelve su id."""
    info = info or {}
    existing = repo.get_by_external(conn, source, external_id.lower())
    if existing is not None:
        refresh_details(conn, source, {existing["external_id"]: info} if info else {})
        return existing["id"]
    label = (info.get("name") or "").strip() or external_id
    return create_group(conn, name=suggest_name(conn, info.get("name"), external_id), label=label[:200],
                        description=(info.get("description") or "")[:500], source=source, external_id=external_id)


# --------------------------------------------------------------------------- carpetas compartidas

def is_member_by_role(user) -> bool:
    return user["role"] == ADMIN


def _refs(group) -> set[str]:
    refs = {group["name"]}
    if group["external_id"]:
        refs.add(group["external_id"])
    return refs


def share_level(group, share: dict) -> str:
    """Acceso que da el grupo a la carpeta: ``none``, ``read`` o ``write``."""
    refs = _refs(group)
    matched = refs.intersection(share["groups"])
    if not matched:
        return "none"
    if share["read_only"] or matched <= set(share.get("read_only_groups", [])):
        return "read"
    return "write"


def shares_of(group, shares: list[dict]) -> list[dict]:
    result = []
    for share in shares:
        level = share_level(group, share)
        if level != "none":
            result.append({**share, "level": level})
    return result


def open_to_everyone(share: dict) -> bool:
    return "*" in share["users"]


def apply_access(shares: list[dict], group, share_name: str, level: str) -> list[dict]:
    """Copia de ``shares`` con el acceso del grupo a la carpeta cambiado."""
    if level not in ACCESS_LEVELS:
        raise GroupError(_("Invalid access level: %(level)s", level=level))
    refs = _refs(group)
    result = copy.deepcopy(shares)
    for share in result:
        if share["name"] != share_name:
            continue
        current = [g for g in share["groups"] if g not in refs]
        read_only = [g for g in share.get("read_only_groups", []) if g not in refs]
        if level != "none":
            current.append(group["name"])
            if level == "read" and not share["read_only"]:
                read_only.append(group["name"])
        share["groups"] = current
        share["read_only_groups"] = read_only
    return result

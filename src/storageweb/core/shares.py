"""Carpetas compartidas vistas «por carpeta»: quién entra y con qué permiso.

En la configuración cada carpeta guarda cuatro listas (``users``, ``read_only_users``, ``groups``,
``read_only_groups``). Aquí se ven como una lista de *entradas* ``{"kind", "ref", "level"}``:

- ``kind``: ``all`` (todos los usuarios, ``*``), ``user`` o ``group``;
- ``ref``: el usuario o el grupo (identificador, nombre de grupo del sistema u Object ID de Entra ID);
- ``level``: ``write`` o ``read``.

Las reglas de acceso efectivas están en :func:`core.storage.share_access`.
"""
from __future__ import annotations

import copy

from ..i18n import _, _l
from . import locations
from .alerts import alert, source

ENTRY_KINDS = ("all", "user", "group")
ENTRY_LEVELS = ("write", "read")
LEVEL_LABELS = {"write": _l("Read and write"), "read": _l("Read only")}
KIND_LABELS = {"all": _l("everyone"), "user": _l("user"), "group": _l("group")}


class ShareError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def entries(share: dict) -> list[dict]:
    ro_users = set(share.get("read_only_users", []))
    ro_groups = set(share.get("read_only_groups", []))
    result = []
    if "*" in share["users"]:
        result.append({"kind": "all", "ref": "*", "level": "read" if "*" in ro_users else "write"})
    result += [{"kind": "user", "ref": u, "level": "read" if u in ro_users else "write"}
               for u in share["users"] if u != "*"]
    result += [{"kind": "group", "ref": grp, "level": "read" if grp in ro_groups else "write"}
               for grp in share["groups"]]
    return result


def with_entries(share: dict, items: list[dict]) -> dict:
    """Copia de ``share`` con las listas de acceso rehechas a partir de ``items`` (sin duplicados)."""
    users, ro_users, groups, ro_groups = [], [], [], []
    for item in items:
        kind, ref, level = item["kind"], item["ref"].strip().lower(), item["level"]
        if kind not in ENTRY_KINDS or level not in ENTRY_LEVELS:
            raise ShareError(_("Invalid access entry."))
        if kind == "all":
            ref = "*"
        if not ref:
            continue
        if kind == "user" and ref == "*":
            kind = "all"
        target, ro = (groups, ro_groups) if kind == "group" else (users, ro_users)
        if ref in target:
            continue
        target.append(ref)
        if level == "read":
            ro.append(ref)
    return {**share, "users": users, "read_only_users": ro_users, "groups": groups, "read_only_groups": ro_groups}


def rename_user(shares: list[dict], old: str, new: str) -> list[dict] | None:
    """Las carpetas con el nombre de usuario cambiado en sus listas (``users`` y ``read_only_users``); ``None`` si
    ninguna lo nombraba."""
    old, new = old.lower(), new.lower()
    changed = False
    result = copy.deepcopy(shares)
    for share in result:
        for key in ("users", "read_only_users"):
            values = share.get(key) or []
            if any(v.lower() == old for v in values):
                share[key] = [new if v.lower() == old else v for v in values]
                changed = True
    return result if changed else None


def find(shares: list[dict], name: str) -> dict | None:
    return next((s for s in shares if s["name"] == name), None)


def replace(shares: list[dict], original: str | None, share: dict) -> list[dict]:
    """Copia de ``shares`` con ``original`` sustituida por ``share`` (o añadida si ``original`` es None)."""
    result = copy.deepcopy(shares)
    if original is None:
        if find(result, share["name"]) is not None:
            raise ShareError(_("Duplicate or reserved shared folder name: %(name)s", name=repr(share["name"])))
        return result + [share]
    for i, current in enumerate(result):
        if current["name"] == original:
            result[i] = share
            return result
    raise ShareError(_("The shared folder %(name)s does not exist.", name=repr(original)))


def remove(shares: list[dict], name: str) -> list[dict]:
    return [copy.deepcopy(s) for s in shares if s["name"] != name]


@source("shares", order=20)
def _missing_folders(ctx):
    """Carpetas en el disco del servidor que no existen (las remotas se comprueban al abrirlas)."""
    cfg = ctx.cfg
    if cfg["storage"]["create_shares"]:
        return []
    return [alert("warn", "share_missing", _("The shared folder «%(label)s» does not exist on the server",
                                             label=share["label"]),
                  share["path"], "folders", _("Review the folder"), f"share-{share['name']}")
            for share in cfg["storage"]["shares"]
            if locations.local_exists(share.get("location", ""), share["path"]) is False]

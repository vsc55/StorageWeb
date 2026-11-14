"""Buscador de la administración (Ctrl+K y ``/admin/search``).

Busca en páginas (``nav.ZONES``), ajustes (lleva al campo exacto: ``#f-<ruta-con-guiones>``, el
ancla que deja la macro ``origin``), acciones frecuentes, usuarios, grupos y carpetas compartidas.
No distingue mayúsculas ni tildes y exige que aparezcan todas las palabras.
"""
from __future__ import annotations

import unicodedata
from sqlite3 import Connection

from flask import url_for

from ..core import groups as group_core
from ..db.repositories import groups as group_repo
from ..db.repositories import users
from ..i18n import _, _l
from ..settings import SECRET_PATHS, fields, get_path
from . import nav

MAX_RESULTS = 30
MAX_PER_ENTITY = 6

GROUP_LABELS = {"action": _l("Actions"), "page": _l("Pages"), "setting": _l("Settings"), "user": _l("Users"),
                "group": _l("Groups"), "share": _l("Shared folders")}

# (icono, título, endpoint, argumentos, ancla, sinónimos)
ACTIONS = (
    ("user", _l("New user"), "admin.user_new", {}, "", "alta crear usuario cuenta add create"),
    ("users", _l("New group"), "groups.new", {}, "", "crear grupo add create"),
    ("folder", _l("New shared folder"), "access.folder_new", {}, "", "crear carpeta compartida share add create"),
    ("download", _l("Create a backup now"), "settings.section", {"name": "backups"}, "backups",
     "copia seguridad backup ahora"),
    ("lock", _l("Block an IP address"), "settings.section", {"name": "ips"}, "ip-rules", "ip bloquear ban"),
    ("key", _l("Renew the Entra ID secret"), "settings.section", {"name": "auth"}, "f-auth-entra-secret_expires",
     "secreto entra renovar rotar microsoft secret rotate"),
    ("globe", _l("Register the application in Entra ID"), "settings.entra_register_page", {}, "",
     "entra registrar app microsoft"),
    ("logout", _l("Close all sessions"), "settings.section", {"name": "sessions"}, "", "sesiones cerrar todas logout"),
    ("audit", _l("Export the audit log (CSV)"), "admin.audit_export", {}, "", "auditoría exportar csv"),
    ("sync", _l("Compact the database"), "settings.section", {"name": "backups"}, "", "base datos compactar vacuum"),
)


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _matches(terms: list[str], *fields) -> bool:
    haystack = _norm(" ".join(str(f) for f in fields if f))
    return all(term in haystack for term in terms)


def _where(page_key: str) -> str:
    return f"{nav.ZONE_OF[page_key].label} → {nav.PAGES[page_key].label}"


def _value(cfg: dict, path: str) -> str:
    """Valor actual para mostrarlo al lado del ajuste (sin secretos ni logo)."""
    if path in SECRET_PATHS or path == "branding.logo":
        return ""
    return fields.display(path, get_path(cfg, path), limit=40)


def _item(kind: str, title, where: str, url: str, hint: str = "", icon: str = "") -> dict:
    return {"kind": kind, "group": str(GROUP_LABELS[kind]), "title": str(title), "path": where, "url": url,
            "hint": hint, "icon": icon}


def find(query: str, conn: Connection, cfg: dict) -> list[dict]:
    terms = _norm(query).split()
    results: list[dict] = []

    for icon, title, endpoint, args, anchor, words in ACTIONS:
        if not terms or _matches(terms, title, words):
            url = url_for(endpoint, **args) + (f"#{anchor}" if anchor else "")
            results.append(_item("action", title, "", url, icon=icon))

    for zone in nav.ZONES:
        for page in zone.pages:
            if not terms or _matches(terms, page.label, zone.label, page.hint, page.words):
                results.append(_item("page", page.label, str(zone.label), page.url(), str(page.hint), zone.icon))

    if terms:
        for path, info in fields.FIELDS.items():  # los ajustes con etiqueta en la web
            if not info.page or not (info.label or path.startswith("permissions.user.")):
                continue
            label, words, page = fields.label(path), info.words, info.page
            if _matches(terms, label, words, path, nav.PAGES[page].label):
                results.append(_item("setting", label, _where(page),
                                     nav.PAGES[page].url() + "#f-" + path.replace(".", "-"), _value(cfg, path)))

        # Se filtra aquí y no en SQL para no distinguir tildes (LIKE sí las distingue)
        found = [u for u in users.list_all(conn) if _matches(terms, u["username"], u["display_name"], u["email"])]
        for row in found[:MAX_PER_ENTITY]:
            results.append(_item("user", row["display_name"] or row["username"],
                                 f"{row['username']} · {row['source']}", url_for("admin.user_edit", user_id=row["id"]),
                                 "" if row["enabled"] else _("Disabled"), "user"))
        found = [grp for grp in group_repo.list_all(conn)
                 if _matches(terms, grp["name"], group_core.label(grp), grp["description"], grp["external_id"])]
        for row in found[:MAX_PER_ENTITY]:
            results.append(_item("group", group_core.label(row), row["name"],
                                 url_for("groups.edit", group_id=row["id"]), icon="users"))
        for share in cfg["storage"]["shares"]:
            if _matches(terms, share["label"], share["name"], share["path"]):
                results.append(_item("share", share["label"], f"/f/{share['name']}",
                                     url_for("access.folder", name=share["name"]), icon="folder"))
    return results[:MAX_RESULTS]

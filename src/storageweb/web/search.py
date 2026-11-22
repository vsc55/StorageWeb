"""Buscador de la administración (Ctrl+K y ``/admin/search``).

Aquí solo está lo genérico: páginas (``nav.ZONES``) y ajustes (lleva al campo exacto:
``#f-<ruta-con-guiones>``, el ancla que deja la macro ``origin``). Lo demás lo aporta el módulo que
sabe de cada cosa:

- :func:`action` registra una acción frecuente («Nuevo usuario», «Crear una copia ahora»…);
- :func:`provider` registra una función que busca entidades (usuarios, grupos, carpetas…).

Las vistas se importan todas al registrar los blueprints, así que al buscar ya están registradas.
No distingue mayúsculas ni tildes y exige que aparezcan todas las palabras.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from sqlite3 import Connection

from flask import url_for

from ..i18n import _l
from ..settings import fields, get_path, is_secret
from . import nav

MAX_RESULTS = 30
MAX_PER_ENTITY = 6


@dataclass(frozen=True)
class Action:
    icon: str
    title: object
    endpoint: str
    args: dict = field(default_factory=dict)
    anchor: str = ""
    words: str = ""          # sinónimos (en los dos idiomas)
    order: int = 50


@dataclass(frozen=True)
class Provider:
    kind: str
    label: object            # título del grupo de resultados
    find: Callable[[list[str], Connection, dict], list[dict]]
    order: int = 50


_ACTIONS: list[Action] = []
_PROVIDERS: dict[str, Provider] = {}
GROUP_LABELS = {"action": _l("Actions"), "page": _l("Pages"), "setting": _l("Settings")}


def action(icon: str, title, endpoint: str, args: dict | None = None, anchor: str = "", words: str = "",
           order: int = 50) -> None:
    """Registra una acción frecuente (se muestra también sin escribir nada)."""
    new = Action(icon, title, endpoint, args or {}, anchor, words, order)
    if all((a.endpoint, a.anchor, str(a.title)) != (new.endpoint, new.anchor, str(new.title)) for a in _ACTIONS):
        _ACTIONS.append(new)
        _ACTIONS.sort(key=lambda a: a.order)


def provider(kind: str, label, order: int = 50):
    """Registra ``fn(terms, conn, cfg) -> [item(...)]`` como buscador de un tipo de entidad."""
    def decorate(fn):
        _PROVIDERS.setdefault(kind, Provider(kind, label, fn, order))
        GROUP_LABELS.setdefault(kind, label)
        return fn
    return decorate


def norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def matches(terms: list[str], *values) -> bool:
    haystack = norm(" ".join(str(v) for v in values if v))
    return all(term in haystack for term in terms)


def item(kind: str, title, where: str, url: str, hint: str = "", icon: str = "") -> dict:
    return {"kind": kind, "group": str(GROUP_LABELS[kind]), "title": str(title), "path": where, "url": url,
            "hint": hint, "icon": icon}


def _where(page_key: str) -> str:
    return f"{nav.ZONE_OF[page_key].label} → {nav.PAGES[page_key].label}"


def _value(cfg: dict, path: str) -> str:
    """Valor actual para mostrarlo al lado del ajuste (sin secretos ni logo)."""
    if is_secret(path) or path == "branding.logo":
        return ""
    return fields.display(path, get_path(cfg, path), limit=40)


def find(query: str, conn: Connection, cfg: dict) -> list[dict]:
    terms = norm(query).split()
    results: list[dict] = []

    for a in _ACTIONS:
        if not terms or matches(terms, a.title, a.words):
            url = url_for(a.endpoint, **a.args) + (f"#{a.anchor}" if a.anchor else "")
            results.append(item("action", a.title, "", url, icon=a.icon))

    for zone in nav.ZONES:
        for page in zone.pages:
            if not terms or matches(terms, page.label, zone.label, page.hint, page.words):
                results.append(item("page", page.label, str(zone.label), page.url(), str(page.hint), zone.icon))

    if terms:
        for path, info in fields.FIELDS.items():  # los ajustes con etiqueta en la web
            if not info.page or not (info.label or path.startswith("permissions.user.")):
                continue
            label, words, page = fields.label(path), info.words, info.page
            if matches(terms, label, words, path, nav.PAGES[page].label):
                # Los permisos de Usuario se editan en la ficha de ese rol, no en la página de Roles
                url = (url_for("roles.edit", key="user") if path.startswith("permissions.user.")
                       else nav.PAGES[page].url() + "#f-" + path.replace(".", "-"))
                results.append(item("setting", label, _where(page), url, _value(cfg, path)))
        for p in sorted(_PROVIDERS.values(), key=lambda p: (p.order, p.kind)):
            results.extend(p.find(terms, conn, cfg)[:MAX_PER_ENTITY])
    return results[:MAX_RESULTS]

"""Funciones auxiliares compartidas por los tests."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from werkzeug.security import generate_password_hash

PASSWORD = "contraseña-segura"


def deep_update(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def add_user(app, username: str, password: str | None = PASSWORD, source: str = "local",
             role: str = "user", **kw) -> int:
    from storageweb.db.repositories import users
    from storageweb.web.context import get_db

    with app.app_context():
        return users.create(get_db(), username=username, source=source, role=role,
                            password_hash=generate_password_hash(password) if password else None, **kw)


def visible(html: str) -> str:
    """HTML sin el catálogo JSON de textos del JavaScript (contiene textos que no se muestran)."""
    return re.sub(r'<script type="application/json" id="i18n-messages">.*?</script>', "", html, flags=re.S)


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match, "no se encontró el token CSRF en la página"
    return match.group(1)


def get_csrf(client, url: str = "/login") -> str:
    return csrf_from(client.get(url).get_data(as_text=True))


def login(client, username: str, password: str = PASSWORD, next_url: str = ""):
    token = get_csrf(client)
    return client.post("/login", data={"username": username, "password": password,
                                       "_csrf": token, "next": next_url})


def settings_form(client, section: str = "general") -> dict:
    """Lee el formulario de /admin/settings/<section> tal como lo enviaría el navegador."""
    return page_form(client, f"/admin/settings/{section}")


class _FormReader(HTMLParser):
    """Lo que enviaría el navegador al pulsar «Guardar» en el formulario ``settings-form`` de una página.

    Como el navegador: sin controles desactivados (ni dentro de un ``<fieldset disabled>``), sin el
    contenido de ``<template>``, solo las casillas marcadas y, de cada ``<select>``, la opción elegida
    (o la primera).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.data: dict[str, list[str]] = {}
        self.in_form = False
        self.template = 0
        self.disabled_fieldsets = 0
        self.fieldsets: list[bool] = []
        self.select: dict | None = None
        self.textarea: dict | None = None

    def _add(self, name, value):
        self.data.setdefault(name, []).append(value)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and "settings-form" in (a.get("class") or "").split() and "data-watch" in a:
            self.in_form = True
            return
        if not self.in_form:
            return
        if tag == "template":
            self.template += 1
        elif tag == "fieldset":
            disabled = "disabled" in a
            self.fieldsets.append(disabled)
            self.disabled_fieldsets += disabled
        if self.template or self.disabled_fieldsets:
            return
        off = "disabled" in a
        if tag == "input" and a.get("name") and not off:
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self._add(a["name"], a.get("value") or "on")
            elif kind not in ("submit", "button", "file", "reset"):
                self._add(a["name"], a.get("value") or "")
        elif tag == "select" and a.get("name") and not off:
            self.select = {"name": a["name"], "first": None, "chosen": None}
        elif tag == "option" and self.select is not None:
            value = a.get("value", "")
            if self.select["first"] is None:
                self.select["first"] = value
            if "selected" in a:
                self.select["chosen"] = value
        elif tag == "textarea" and a.get("name") and not off:
            self.textarea = {"name": a["name"], "text": ""}

    def handle_data(self, data):
        if self.textarea is not None:
            self.textarea["text"] += data

    def handle_endtag(self, tag):
        if not self.in_form:
            return
        if tag == "form":
            self.in_form = False
        elif tag == "template":
            self.template -= 1
        elif tag == "fieldset" and self.fieldsets:
            self.disabled_fieldsets -= self.fieldsets.pop()
        elif tag == "select" and self.select is not None:
            chosen = self.select["chosen"] if self.select["chosen"] is not None else self.select["first"]
            self._add(self.select["name"], chosen or "")
            self.select = None
        elif tag == "textarea" and self.textarea is not None:
            self._add(self.textarea["name"], self.textarea["text"])
            self.textarea = None


def page_form(client, url: str) -> dict:
    """Lee el formulario de ajustes (``settings-form``) de una página tal como lo enviaría el navegador."""
    reader = _FormReader()
    reader.feed(client.get(url).get_data(as_text=True))
    assert reader.data, f"{url} no tiene formulario de ajustes"
    return reader.data

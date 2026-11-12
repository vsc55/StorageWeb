"""Funciones auxiliares compartidas por los tests."""
from __future__ import annotations

import re

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


def settings_form(client) -> dict:
    """Lee el formulario de /admin/settings tal como lo enviaría el navegador."""
    html = client.get("/admin/settings").get_data(as_text=True)
    form = re.search(r'<form method="post" class="settings">(.*?)</form>', html, re.S).group(1)
    data: dict = {}
    for m in re.finditer(r'<input([^>]*)>', form):
        attrs = dict(re.findall(r'(\w[\w-]*)="([^"]*)"', m.group(1)))
        name, typ = attrs.get("name"), attrs.get("type", "text")
        if not name:
            continue
        if typ == "checkbox":
            if " checked" in m.group(1):
                data.setdefault(name, []).append("on")
        else:
            data.setdefault(name, []).append(attrs.get("value", ""))
    for m in re.finditer(r'<select name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
        sel = re.search(r'<option value="([^"]*)"[^>]*selected', m.group(2)) or \
            re.search(r'<option value="([^"]*)"', m.group(2))
        data.setdefault(m.group(1), []).append(sel.group(1))
    for m in re.finditer(r'<textarea name="([^"]+)"[^>]*>(.*?)</textarea>', form, re.S):
        data[m.group(1)] = [m.group(2)]
    return data

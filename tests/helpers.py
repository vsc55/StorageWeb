"""Funciones auxiliares compartidas por los tests."""
from __future__ import annotations

import base64
import functools
import importlib.util
import os
import re
import subprocess
import sys
import threading
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

from werkzeug.security import generate_password_hash

PASSWORD = "contraseña-segura"
ROOT = Path(__file__).resolve().parents[1]  # la raíz del repositorio


APPS: list = []  # las aplicaciones que crea make_app (U y G buscan en la última)


def _public(table: str, x) -> str:
    """Identificador público (``uid``) de un usuario o grupo: de la fila si se pasa una, o buscando su id numérico
    en la última aplicación creada."""
    if hasattr(x, "keys") and "uid" in x.keys():
        return x["uid"]
    from storageweb.web.context import get_db
    with APPS[-1].app_context():
        row = get_db().execute(f"SELECT uid FROM {table} WHERE id = ?", (int(x),)).fetchone()  # noqa: S608
    assert row is not None, f"{table} {x} no existe"
    return row["uid"]


def U(x) -> str:  # noqa: N802 (corto a propósito: va dentro de las direcciones de las pruebas)
    """Identificador público del usuario (fila o id numérico): el de /admin/users/<uid>."""
    return _public("users", x)


def G(x) -> str:  # noqa: N802
    """Identificador público del grupo (fila o id numérico): el de /admin/groups/<uid>."""
    return _public("groups", x)


def stored_settings(app, profile: str = "default") -> dict:
    """Los ajustes web guardados del perfil, tal cual (los secretos, cifrados si se guardaron desde la web), con las
    carpetas, ubicaciones y cuotas de grupo de sus tablas (solo si hay)."""
    from storageweb.settings import store
    from storageweb.web.context import get_db
    with app.app_context():
        doc = store.read_doc(get_db(), profile)
        entities = {k: v for k, v in store.read_entities(get_db(), profile).items() if v}
    if entities:
        doc.setdefault("storage", {}).update(entities)
    return doc


def store_settings(app, doc: dict, profile: str = "default") -> None:
    """Deja los ajustes web del perfil exactamente como ``doc`` (como si los hubiera guardado un admin); las
    carpetas, ubicaciones y cuotas de grupo que traiga van a sus tablas."""
    from storageweb.settings import store
    from storageweb.web.context import get_db
    with app.app_context():
        conn = get_db()
        current = store.read_entities(conn, profile)
        wanted = {k: (doc.get("storage") or {}).get(k, [] if k != "group_quotas" else {})
                  for k in ("shares", "locations", "group_quotas")}
        store.apply_entities(conn, profile, current, wanted, "tests")
        settings_only = {**doc, "storage": {k: v for k, v in (doc.get("storage") or {}).items() if k not in wanted}}
        if not settings_only["storage"]:
            settings_only.pop("storage")
        store.put_doc(conn, profile, settings_only, "tests")


def update_settings(app, profile: str = "default", **sections) -> None:
    """Cambia ajustes web: ``update_settings(app, storage={"quota_enforce": False}, app_name="X")``."""
    current = stored_settings(app, profile)
    for name, value in sections.items():
        if isinstance(value, dict):
            current.setdefault(name, {}).update(value)
        else:
            current[name] = value
    store_settings(app, current, profile)


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


def signed_in(app, username: str = "ana", *, csrf_url: str | None = "/f/home/", create: bool = True,
              password: str = PASSWORD, client=None, **user_kw):
    """Crea la cuenta (salvo ``create=False``; ``user_kw`` va a :func:`add_user`), inicia sesión en un cliente nuevo
    (o en ``client``) y lee el token CSRF de ``csrf_url`` (``None``: no visita ninguna página y el token es ``None``).
    Devuelve ``(client, token)``."""
    if create:
        add_user(app, username, password, **user_kw)
    client = client or app.test_client()
    resp = login(client, username, password)
    assert resp.status_code == 302, f"{username} no pudo iniciar sesión"
    return client, (get_csrf(client, csrf_url) if csrf_url else None)


def get_user(app, username: str = "ana"):
    """La fila de ``users`` de ``username`` (o ``None``)."""
    from storageweb.db.repositories import users
    from storageweb.web.context import get_db
    with app.app_context():
        return users.get_by_username(get_db(), username)


def api_token(app, username: str = "ana", *, scope: str = "write", name: str = "dav", days: int = 0) -> str:
    """Crea un token de API de ``username`` y devuelve su valor en claro."""
    from storageweb.core import tokens
    from storageweb.db.repositories import users
    from storageweb.web.context import get_db
    with app.app_context():
        plain, _id = tokens.create(get_db(), users.get_by_username(get_db(), username), name=name, scope=scope,
                                   days=days)
    return plain


def basic_auth(user: str, secret: str) -> dict:
    """Cabecera ``Authorization: Basic`` (WebDAV con usuario y token o contraseña)."""
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()}


def last_audit(app, action: str):
    """La última fila de la auditoría con esa acción (o ``None``)."""
    from storageweb.web.context import get_db
    with app.app_context():
        return get_db().execute("SELECT * FROM audit_log WHERE action = ? ORDER BY id DESC LIMIT 1",
                                (action,)).fetchone()


def audit_actions(app, n: int = 20) -> list[str]:
    """Las acciones de los ``n`` últimos eventos de la auditoría, del más reciente al más antiguo."""
    from storageweb.db.repositories import audit
    from storageweb.web.context import get_db
    with app.app_context():
        return [r["action"] for r in audit.recent(get_db(), n)]


def config_file(tmp_path, data: dict, name: str = "config.json") -> Path:
    """Escribe ``data`` como el config.json ``tmp_path / name`` y devuelve su ruta."""
    import json
    path = Path(tmp_path) / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def backup_tar(members: dict[str, bytes], manifest: dict | None = None) -> bytes:
    """Un .tar.gz con forma de copia de seguridad hecho a mano: ``manifest.json`` (si se da) y ``members``."""
    import io
    import json
    import tarfile
    if manifest is not None:
        members = {"manifest.json": json.dumps(manifest).encode(), **members}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


# --------------------------------------------------------------------------- CLI y herramientas

def cli_env(lang: str = "es", **over) -> dict:
    """Entorno para lanzar la CLI en otro proceso: textos en ``lang`` y el paquete de ``src/`` aunque no esté
    instalado. ``over`` cambia variables; con ``None``, la quita."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "STORAGEWEB_LANG": lang,
           "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "src"), os.environ.get("PYTHONPATH")]))}
    for key, value in over.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_cli(config, *args, lang: str = "es", input: str | None = None, env: dict | None = None,  # noqa: A002
            ok: bool | None = None) -> subprocess.CompletedProcess:
    """``python -m storageweb --config <config> <args>`` en otro proceso. Con ``ok=True`` exige que acabe bien."""
    res = subprocess.run([sys.executable, "-m", "storageweb", "--config", str(config), *args], input=input,
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                         env=env if env is not None else cli_env(lang))
    if ok:
        assert res.returncode == 0, res.stderr
    return res


def load_tool(relpath: str, name: str | None = None):
    """Carga un script del repositorio (``tools/gen_docs.py``…) como módulo, sin instalarlo."""
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name or path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def node() -> str | None:
    """Node 18 o posterior de este equipo (tools/nodejs.py: ``STORAGEWEB_NODE``, el PATH…), o ``None``."""
    return load_tool("tools/nodejs.py").find_node(18)


@functools.cache
def browser() -> str | None:
    """Edge o Chrome de este equipo (``findBrowser`` de tools/cdp.mjs, con :func:`node`), o ``None``."""
    return load_tool("tools/nodejs.py").find_browser(node()) if node() else None


@contextmanager
def serve_in_thread(app, threads: int = 4):
    """Sirve ``app`` con Waitress en un hilo, en un puerto libre de 127.0.0.1. Devuelve el puerto."""
    from waitress.server import create_server
    server = create_server(app, host="127.0.0.1", port=0, threads=threads)
    closing = threading.Event()

    def run():
        try:
            server.run()
        except OSError:
            if not closing.is_set():   # al cerrar, el select del bucle puede ver el socket ya cerrado (macOS)
                raise
    threading.Thread(target=run, daemon=True).start()
    try:
        yield server.effective_port
    finally:
        closing.set()
        server.close()


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

"""storage.hidden: lo oculto para todos no se lista, no se abre ni se crea (web, WebDAV, API), y la lista de
patrones no llega a los clientes (solo una marca en la ruta concreta que pide un cliente)."""
from __future__ import annotations

import base64
import io

import pytest

from storageweb import patterns
from storageweb.core import tokens
from storageweb.db.repositories import users
from storageweb.settings.errors import ConfigError
from storageweb.web.context import get_db

from tests.helpers import add_user, get_csrf, login, settings_form

HIDDEN = ["Thumbs.db", "*.tmp", ".git/", "/privado", "docs/borradores/*.bak"]


@pytest.fixture
def hidden_app(make_app, tmp_path):
    app = make_app({"storage": {"hidden": HIDDEN}})
    add_user(app, "ana")
    home = tmp_path / "data" / "homes" / "ana"
    for rel in ("ok.txt", "Thumbs.db", "a.tmp", ".git/HEAD", "privado/nomina.pdf", "sub/privado/visible.txt",
                "sub/x.TMP", "docs/borradores/v1.bak", "docs/v1.bak"):
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return app, home


def _dav(app):
    with app.app_context():
        plain, _ = tokens.create(get_db(), users.get_by_username(get_db(), "ana"), name="t", scope="write", days=0)
    client = app.test_client()
    auth = {"Authorization": "Basic " + base64.b64encode(f"ana:{plain}".encode()).decode()}

    def call(method, path, data=b"", extra=None):
        return client.open(path, method=method, data=data, headers={**auth, **(extra or {})})
    return call


def test_patterns_like_gitignore():
    hidden = patterns.matcher(patterns.normalize(HIDDEN))
    assert hidden("Thumbs.db", False) and hidden("a/b/thumbs.db", False)
    assert hidden("x.tmp", False) and hidden("a/x.TMP", False)
    assert hidden(".git", True) and hidden("a/.git/HEAD", False) and not hidden(".git", False)
    assert hidden("privado", True) and hidden("privado/x", False) and not hidden("sub/privado", True)
    assert hidden("docs/borradores/v.bak", False) and not hidden("x/docs/borradores/v.bak", False)
    assert not hidden("ok.txt", False) and not hidden("docs/v1.bak", False)
    for bad in ["!x", "../x", "*", "/", "**", "a\\b"]:
        with pytest.raises(patterns.PatternError):
            patterns.normalize([bad])


def test_web_hides_and_refuses(hidden_app):
    app, home = hidden_app
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    html = client.get("/f/home/").get_data(as_text=True)
    assert "ok.txt" in html
    for name in ("Thumbs.db", "a.tmp", ".git", "privado"):
        assert f">{name}<" not in html, name
    assert "visible.txt" in client.get("/f/home/sub/privado/").get_data(as_text=True), "/privado solo en la raíz"
    assert "x.TMP" not in client.get("/f/home/sub/").get_data(as_text=True)
    for url in ("/f/home/privado/", "/download/home/privado/nomina.pdf", "/download/home/Thumbs.db",
                "/f/home/.git/", "/download/home/docs/borradores/v1.bak"):
        assert client.get(url).status_code == 404, url
    assert client.get("/download/home/docs/v1.bak").status_code == 200

    # No se pueden crear: subir, carpeta nueva, renombrar, ni borrar lo oculto
    resp = client.post("/upload/home/", data={"files": [(io.BytesIO(b"y"), "nuevo.tmp")]},
                       headers={"X-CSRF-Token": token, "Accept": "application/json"}, content_type="multipart/form-data")
    assert resp.get_json()["saved"] == [] and resp.get_json()["errors"]
    assert not (home / "nuevo.tmp").exists()
    client.post("/mkdir/home/", data={"_csrf": token, "name": ".git"})
    client.post("/mkdir/home/sub/", data={"_csrf": token, "name": ".git"})
    assert not (home / "sub" / ".git").exists()
    client.post("/rename/home/ok.txt", data={"_csrf": token, "name": "ok.tmp"})
    assert (home / "ok.txt").exists() and not (home / "ok.tmp").exists()
    assert client.post("/delete/home/Thumbs.db", data={"_csrf": token}).status_code == 404
    assert (home / "Thumbs.db").exists(), "los archivos siguen en el disco"


def test_webdav_hides_with_a_marker_but_never_the_list(hidden_app):
    app, home = hidden_app
    call = _dav(app)
    resp = call("PROPFIND", "/dav/home/", extra={"Depth": "1"})
    body = resp.get_data(as_text=True)
    assert "/dav/home/ok.txt" in body
    for name in ("Thumbs.db", "a.tmp", ".git", "privado"):
        assert f"/dav/home/{name}" not in body, name
    for header, value in resp.headers.items():  # la lista de patrones no se envía
        assert "privado" not in value and "Thumbs" not in value, header

    resp = call("GET", "/dav/home/privado/nomina.pdf")
    assert resp.status_code == 404 and resp.headers.get("X-StorageWeb-Hidden") == "1"
    assert call("GET", "/dav/home/no-existe.txt").headers.get("X-StorageWeb-Hidden") is None
    assert call("PROPFIND", "/dav/home/.git/HEAD", extra={"Depth": "0"}).status_code == 404
    resp = call("PUT", "/dav/home/sub/nuevo.tmp", b"y")
    assert resp.status_code == 403 and resp.headers.get("X-StorageWeb-Hidden") == "1"
    assert not (home / "sub" / "nuevo.tmp").exists()
    assert call("MKCOL", "/dav/home/sub/.git").status_code == 403
    resp = call("MOVE", "/dav/home/ok.txt", extra={"Destination": "http://localhost/dav/home/ok.tmp"})
    assert resp.status_code == 403 and (home / "ok.txt").exists()
    assert call("DELETE", "/dav/home/Thumbs.db").status_code == 404 and (home / "Thumbs.db").exists()


def test_chunked_upload_api_refuses_hidden(hidden_app):
    app, _home = hidden_app
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    resp = client.post("/api/uploads", json={"root": "home", "path": "", "name": "x.tmp", "size": 1}, headers=headers)
    assert resp.status_code == 400
    resp = client.post("/api/uploads", json={"root": "home", "path": "privado", "name": "a.txt", "size": 1}, headers=headers)
    assert resp.status_code == 404


def test_validation_and_admin_form(admin, tmp_path):
    from storageweb.settings.loader import normalize
    with pytest.raises(ConfigError) as exc:
        normalize({"storage": {"hidden": ["!excepcion"]}}, tmp_path / "config.json")
    assert exc.value.field == "storage.hidden"
    assert normalize({"storage": {"hidden": [" a.tmp ", "a.tmp", "# c"]}}, tmp_path / "config.json")["storage"]["hidden"] == ["a.tmp"]
    client, _ = admin
    data = settings_form(client, "files")
    data["hidden"] = ["Thumbs.db\n\n*.tmp\n# comentario\n.git/"]
    assert client.post("/admin/settings/files", data=data).status_code in (200, 302)
    form = settings_form(client, "files")
    assert form["hidden"][0].split("\n") == ["Thumbs.db", "*.tmp", ".git/"]
    data["hidden"] = ["*"]
    resp = client.post("/admin/settings/files", data=data)
    assert resp.status_code == 400 and "storage.hidden" not in resp.headers.get("Location", "")

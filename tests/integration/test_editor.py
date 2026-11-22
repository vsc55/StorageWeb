"""Editor de texto en el navegador (/edit/…, files.edit): permiso «edit», conserva el formato del original,
no pisa los cambios de otro (ETag) y solo edita texto en UTF-8."""
from __future__ import annotations

import re

from storageweb.db.repositories import audit
from storageweb.web.context import get_db

from tests.helpers import get_csrf, signed_in, api_token


def _editor(make_app, **perms):
    app = make_app({"permissions": {"user": {"edit": True, **perms}}})
    c, _ = signed_in(app, "ana", csrf_url=None)
    return app, c, get_csrf(c, "/f/home/")


def _version(page: str) -> str:
    return re.search(r'name="version" value="([^"]+)"', page).group(1)


def test_needs_the_edit_permission(app, logged, home):
    client, csrf = logged
    (home / "notas.txt").write_text("hola\n", encoding="utf-8")
    assert "/edit/home/notas.txt" not in client.get("/view/home/notas.txt").get_data(as_text=True)
    assert client.get("/edit/home/notas.txt").status_code == 403                  # de serie, el rol user no edita
    assert client.post("/edit/home/notas.txt", data={"_csrf": csrf, "text": "x", "version": "1"}).status_code == 403
    assert (home / "notas.txt").read_text(encoding="utf-8") == "hola\n"


def test_edit_and_save_keeps_the_format(make_app, home):
    app, c, csrf = _editor(make_app)
    home.mkdir(parents=True, exist_ok=True)
    (home / "win.txt").write_bytes(b"\xef\xbb\xbfuno\r\ndos\r\n")
    assert 'href="/edit/home/win.txt"' in c.get("/view/home/win.txt").get_data(as_text=True)
    page = c.get("/edit/home/win.txt").get_data(as_text=True)
    assert "uno\ndos</textarea>" in page and "CRLF" in page
    assert re.search(r'name="_csrf" value="([^"]+)"', page).group(1) == csrf      # el formulario lleva el token
    resp = c.post("/edit/home/win.txt", data={"_csrf": csrf, "text": "uno\r\ndos\r\ntres", "version": _version(page)})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/view/home/win.txt")
    assert (home / "win.txt").read_bytes() == b"\xef\xbb\xbfuno\r\ndos\r\ntres\r\n"     # BOM, CRLF y salto final
    (home / "unix.md").write_bytes(b"\n# T\nsin salto")
    page = c.get("/edit/home/unix.md").get_data(as_text=True)
    assert ">\n\n# T\nsin salto</textarea>" in page                                # el salto inicial no se pierde
    c.post("/edit/home/unix.md", data={"_csrf": csrf, "text": "\n# T\nnuevo", "version": _version(page)})
    assert (home / "unix.md").read_bytes() == b"\n# T\nnuevo"
    with app.app_context():
        rows = [r for r in audit.recent(get_db(), 20) if r["action"] == "edit"]
    assert [r["target"] for r in rows] == ["home:/unix.md", "home:/win.txt"]
    assert "Editado" in c.get("/recent").get_data(as_text=True)


def test_conflict_keeps_what_you_wrote(make_app, home):
    _app, c, csrf = _editor(make_app)
    home.mkdir(parents=True, exist_ok=True)
    (home / "a.txt").write_text("original\n", encoding="utf-8")
    stale = _version(c.get("/edit/home/a.txt").get_data(as_text=True))
    (home / "a.txt").write_text("cambiado por otro\n", encoding="utf-8")           # p. ej. por la unidad de red
    resp = c.post("/edit/home/a.txt", data={"_csrf": csrf, "text": "lo mío", "version": stale})
    page = resp.get_data(as_text=True)
    assert resp.status_code == 409 and "lo mío</textarea>" in page and "cambió este archivo" in page
    assert (home / "a.txt").read_text(encoding="utf-8") == "cambiado por otro\n"
    resp = c.post("/edit/home/a.txt", data={"_csrf": csrf, "text": "lo mío", "version": _version(page)})
    assert resp.status_code == 302 and (home / "a.txt").read_text(encoding="utf-8") == "lo mío\n"


def test_only_utf8_text(make_app, home):
    _app, c, _csrf = _editor(make_app)
    home.mkdir(parents=True, exist_ok=True)
    (home / "latin.txt").write_bytes("año".encode("cp1252"))
    (home / "falso.txt").write_bytes(bytes([0, 1]) + b"binario")
    (home / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    for name in ("latin.txt", "falso.txt"):
        assert f'/edit/home/{name}"' not in c.get(f"/view/home/{name}").get_data(as_text=True)
        resp = c.get(f"/edit/home/{name}")
        assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/view/home/{name}")
    assert c.get("/edit/home/foto.png").status_code == 302                         # no se abre en el visor
    assert c.get("/edit/home/no-existe.txt").status_code == 404
    assert c.get("/edit/home/../otro/a.txt").status_code == 404


def test_read_token_cannot_edit(make_app, home):
    from storageweb.core import tokens
    from storageweb.db.repositories import users

    app, _c, _csrf = _editor(make_app)
    home.mkdir(parents=True, exist_ok=True)
    (home / "a.txt").write_text("x\n", encoding="utf-8")
    plain = api_token(app, scope="read", name="r")
    resp = app.test_client().post("/edit/home/a.txt", data={"text": "y", "version": "0"},
                                  headers={"Authorization": f"Bearer {plain}"})
    assert resp.status_code == 403 and (home / "a.txt").read_text(encoding="utf-8") == "x\n"


def test_line_endings_can_be_changed(make_app, home):
    """La barra de estado cambia LF / CRLF: el campo «eol» manda sobre los del original."""
    _app, c, csrf = _editor(make_app)
    home.mkdir(parents=True, exist_ok=True)
    (home / "win.txt").write_bytes(b"uno\r\ndos\r\n")
    page = c.get("/edit/home/win.txt").get_data(as_text=True)
    assert 'name="eol" id="editor-eol-value" value="crlf"' in page
    c.post("/edit/home/win.txt", data={"_csrf": csrf, "text": "uno\ndos", "version": _version(page), "eol": "lf"})
    assert (home / "win.txt").read_bytes() == b"uno\ndos\n"
    page = c.get("/edit/home/win.txt").get_data(as_text=True)
    c.post("/edit/home/win.txt", data={"_csrf": csrf, "text": "uno\ndos", "version": _version(page), "eol": "rara"})
    assert (home / "win.txt").read_bytes() == b"uno\ndos\n"                    # un valor raro: los del archivo

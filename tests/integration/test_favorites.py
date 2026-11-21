"""Favoritos y recientes del explorador (core/favorites.py, files.favorite_toggle y files.recent)."""
from __future__ import annotations

import base64

from storageweb.core import tokens
from storageweb.db.repositories import favorites as repo
from storageweb.db.repositories import users
from storageweb.web.context import get_db

from tests.helpers import add_user, get_csrf, login


def _favs(app, username="ana"):
    with app.app_context():
        user = users.get_by_username(get_db(), username)
        return [(r["root"], r["rel"], r["is_dir"]) for r in repo.list_for_user(get_db(), user["id"])]


def _toggle(client, csrf, root, path):
    return client.post("/favorites", data={"_csrf": csrf, "root": root, "path": path},
                       headers={"Accept": "application/json"})


def test_toggle_and_panel(app, logged, home):
    client, csrf = logged
    (home / "Proyectos" / "Web").mkdir(parents=True)
    (home / "notas.md").write_text("# hola", encoding="utf-8")
    assert _toggle(client, csrf, "home", "Proyectos").get_json() == {"favorite": True}
    assert _toggle(client, csrf, "home", "notas.md").get_json() == {"favorite": True}
    assert _favs(app) == [("home", "Proyectos", 1), ("home", "notas.md", 0)]
    page = client.get("/f/home/").get_data(as_text=True)
    assert "Favoritos" in page and 'href="/f/home/Proyectos"' in page and 'href="/view/home/notas.md"' in page
    assert 'data-fav="1"' in page
    assert _toggle(client, csrf, "home", "Proyectos").get_json() == {"favorite": False}
    assert _favs(app) == [("home", "notas.md", 0)]
    assert _toggle(client, csrf, "home", "no-existe").status_code == 404


def test_favorites_follow_rename_move_and_delete(app, logged, home):
    client, csrf = logged
    (home / "A" / "sub").mkdir(parents=True)
    (home / "B").mkdir()
    (home / "A" / "sub" / "f.txt").write_text("x", encoding="utf-8")
    for path in ("A", "A/sub", "A/sub/f.txt"):
        _toggle(client, csrf, "home", path)
    client.post("/rename/home/A", data={"_csrf": csrf, "name": "Z"})
    assert sorted(r[1] for r in _favs(app)) == ["Z", "Z/sub", "Z/sub/f.txt"]
    client.post("/transfer", data={"_csrf": csrf, "action": "move", "root": "home", "items": ["Z/sub"],
                                   "dest_root": "home", "dest_path": "B"}, headers={"Accept": "application/json"})
    assert sorted(r[1] for r in _favs(app)) == ["B/sub", "B/sub/f.txt", "Z"]
    client.post("/delete/home/B", data={"_csrf": csrf})
    assert [r[1] for r in _favs(app)] == ["Z"]


def test_home_is_per_user_and_webdav_keeps_them(app, logged, home):
    client, csrf = logged
    (home / "Docs").mkdir()
    _toggle(client, csrf, "home", "Docs")
    add_user(app, "luis")
    luis_home = home.parent / "luis"
    (luis_home / "Docs").mkdir(parents=True)
    other = app.test_client()
    login(other, "luis")
    other_csrf = get_csrf(other, "/f/home/")
    other.post("/rename/home/Docs", data={"_csrf": other_csrf, "name": "Otros"})   # su carpeta, no la de ana
    assert _favs(app) == [("home", "Docs", 1)]

    with app.app_context():
        plain, _id = tokens.create(get_db(), users.get_by_username(get_db(), "ana"), name="dav", scope="write", days=0)
    auth = {"Authorization": "Basic " + base64.b64encode(f"ana:{plain}".encode()).decode()}
    dav = app.test_client()
    assert dav.open("/dav/home/Docs", method="MOVE", headers={**auth, "Destination": "/dav/home/Movida"}).status_code == 201
    assert _favs(app) == [("home", "Movida", 1)]
    assert dav.open("/dav/home/Movida", method="DELETE", headers=auth).status_code == 204
    assert _favs(app) == []


def test_recent_from_the_web_only(app, logged, home):
    client, _csrf = logged
    (home / "informe.zip").write_bytes(b"PK")
    (home / "notas.md").write_text("# hola", encoding="utf-8")
    client.get("/download/home/informe.zip")
    client.get("/view/home/notas.md")
    with app.app_context():
        plain, _id = tokens.create(get_db(), users.get_by_username(get_db(), "ana"), name="dav", scope="read", days=0)
    auth = {"Authorization": "Basic " + base64.b64encode(f"ana:{plain}".encode()).decode()}
    (home / "sincronizado.txt").write_text("x", encoding="utf-8")
    app.test_client().get("/dav/home/sincronizado.txt", headers=auth)      # unidad de red: no cuenta
    page = client.get("/recent").get_data(as_text=True)
    assert 'href="/download/home/informe.zip"' in page and 'href="/view/home/notas.md"' in page
    assert "sincronizado.txt" not in page
    assert page.index("notas.md") < page.index("informe.zip")              # lo último, primero


def test_remove_from_the_list(app, logged, home):
    """La X de la lista de favoritos: los quita, también si lo que señalaban ya no existe."""
    client, csrf = logged
    (home / "Docs").mkdir(parents=True)
    (home / "borrado.txt").write_text("x", encoding="utf-8")
    _toggle(client, csrf, "home", "Docs")
    _toggle(client, csrf, "home", "borrado.txt")
    page = client.get("/f/home/").get_data(as_text=True)
    assert 'class="fav-remove"' in page and "Quitar «Docs» de favoritos" in page
    (home / "borrado.txt").unlink()                                           # borrado por fuera de StorageWeb
    resp = client.post("/favorites", data={"_csrf": csrf, "action": "remove", "root": "home", "path": "borrado.txt"},
                       headers={"Accept": "application/json"})
    assert resp.get_json() == {"favorite": False}
    resp = client.post("/favorites", data={"_csrf": csrf, "action": "remove", "root": "home", "path": "Docs",
                                           "next": "/f/home/Docs"})
    assert resp.status_code == 302 and resp.location.endswith("/f/home/Docs")    # sin JavaScript: vuelve donde estaba
    assert _favs(app) == []
    assert client.post("/favorites", data={"_csrf": csrf, "action": "remove", "root": "home",
                                           "path": "../otro"}).status_code == 404

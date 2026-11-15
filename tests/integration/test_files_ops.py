"""Explorador: mover y copiar, descargar como ZIP y buscar por nombre (core/files.py, web/views/files.py)."""
from __future__ import annotations

import io
import zipfile

import pytest

from storageweb.core import files as files_core

from tests.helpers import add_user, get_csrf, login


@pytest.fixture
def setup(make_app, tmp_path):
    """Ana con su carpeta personal, una compartida donde escribe y otra de solo lectura."""
    shared, ro = tmp_path / "equipo", tmp_path / "ro"
    for d in (shared, ro):
        d.mkdir()
    (ro / "manual.pdf").write_bytes(b"pdf")
    app = make_app({"storage": {"shares": [
        {"name": "equipo", "label": "Equipo", "path": str(shared), "users": ["*"]},
        {"name": "lectura", "label": "Lectura", "path": str(ro), "users": ["*"], "read_only": True},
    ], "hidden": ["*.tmp"]}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    home = tmp_path / "data" / "homes" / "ana"
    for rel, data in (("Informes/2026/año.txt", b"uno"), ("Informes/resumen.md", b"dos"), ("foto.jpg", b"jpg"),
                      ("basura.tmp", b"x"), (".oculto", b"y"), ("Vacía/.keep", None)):
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            p.write_bytes(data)
    return app, client, token, home, shared, ro


def _transfer(client, token, action, items, dest_root, dest_path, root="home"):
    return client.post("/transfer", data={"_csrf": token, "action": action, "root": root, "items": items,
                                         "dest_root": dest_root, "dest_path": dest_path},
                       headers={"Accept": "application/json"})


# --------------------------------------------------------------------------- mover y copiar

def test_move_and_copy_in_the_same_folder_of_storageweb(setup):
    _app, client, token, home, _shared, _ro = setup
    (home / "Archivo").mkdir()
    resp = _transfer(client, token, "move", ["foto.jpg", "Informes"], "home", "Archivo")
    assert resp.status_code == 200 and resp.get_json() == {"done": ["foto.jpg", "Informes"], "errors": []}
    assert (home / "Archivo" / "foto.jpg").exists() and (home / "Archivo" / "Informes" / "2026" / "año.txt").exists()
    assert not (home / "foto.jpg").exists() and not (home / "Informes").exists()
    resp = _transfer(client, token, "copy", ["Archivo/foto.jpg"], "home", "")
    assert resp.get_json()["done"] == ["foto.jpg"]
    assert (home / "foto.jpg").read_bytes() == (home / "Archivo" / "foto.jpg").read_bytes() == b"jpg"


def test_move_and_copy_between_folders_of_storageweb(setup):
    _app, client, token, home, shared, _ro = setup
    assert _transfer(client, token, "copy", ["Informes"], "equipo", "").get_json()["done"] == ["Informes"]
    assert (shared / "Informes" / "2026" / "año.txt").read_bytes() == b"uno" and (home / "Informes").exists()
    assert _transfer(client, token, "move", ["foto.jpg"], "equipo", "Informes").get_json()["done"] == ["foto.jpg"]
    assert (shared / "Informes" / "foto.jpg").exists() and not (home / "foto.jpg").exists()


def test_never_overwrites_and_rejects_impossible_moves(setup):
    _app, client, token, home, _shared, _ro = setup
    (home / "Otra").mkdir()
    (home / "Otra" / "foto.jpg").write_bytes(b"otra")
    data = _transfer(client, token, "move", ["foto.jpg"], "home", "Otra").get_json()
    assert data["done"] == [] and "ya existe" in data["errors"][0]
    assert (home / "Otra" / "foto.jpg").read_bytes() == b"otra" and (home / "foto.jpg").exists()
    assert "dentro de sí" in _transfer(client, token, "move", ["Informes"], "home", "Informes/2026").get_json()["errors"][0]
    assert "ya está" in _transfer(client, token, "move", ["foto.jpg"], "home", "").get_json()["errors"][0]
    resp = _transfer(client, token, "move", ["no-existe.txt"], "home", "Otra")
    assert resp.status_code == 400 and "ya no existe" in resp.get_json()["errors"][0]
    data = _transfer(client, token, "copy", ["../../etc/passwd"], "home", "Otra").get_json()
    assert data["done"] == [] and data["errors"][0].startswith("Ruta no válida")
    assert not (home / "Otra" / "passwd").exists()


def test_permissions_like_webdav(setup):
    _app, client, token, _home, _shared, ro = setup
    assert _transfer(client, token, "copy", ["foto.jpg"], "lectura", "").status_code == 403   # no se puede subir allí
    assert _transfer(client, token, "move", ["manual.pdf"], "home", "", root="lectura").status_code == 403
    assert _transfer(client, token, "copy", ["manual.pdf"], "home", "", root="lectura").get_json()["done"] == ["manual.pdf"]
    assert (ro / "manual.pdf").exists()
    assert _transfer(client, token, "copy", ["foto.jpg"], "home", "basura-carpeta.tmp").status_code == 404  # oculta
    assert client.post("/transfer", data={"action": "move", "root": "home", "items": ["foto.jpg"],
                                          "dest_root": "home", "dest_path": "Vacía"}).status_code == 400  # sin CSRF


def test_roots_for_the_destination_picker(setup):
    _app, client, _token, _home, _shared, _ro = setup
    roots = {r["name"]: r for r in client.get("/roots").get_json()["roots"]}
    assert set(roots) == {"home", "equipo", "lectura"}
    assert roots["lectura"]["read_only"] and "upload" not in roots["lectura"]["permissions"]
    assert "upload" in roots["equipo"]["permissions"]


# --------------------------------------------------------------------------- ZIP

def test_folder_as_zip(setup):
    _app, client, _token, _home, _shared, _ro = setup
    resp = client.get("/zip/home/Informes")
    assert resp.status_code == 200 and resp.mimetype == "application/zip"
    assert "Informes.zip" in resp.headers["Content-Disposition"] and resp.headers["Content-Security-Policy"] == "sandbox"
    zf = zipfile.ZipFile(io.BytesIO(resp.get_data()))
    assert set(zf.namelist()) == {"Informes/", "Informes/2026/", "Informes/2026/año.txt", "Informes/resumen.md"}
    assert zf.read("Informes/2026/año.txt") == b"uno" and zf.testzip() is None


def test_selection_as_zip_without_hidden_files(setup):
    _app, client, token, _home, _shared, _ro = setup
    resp = client.post("/zip", data={"_csrf": token, "root": "home",
                                     "items": ["foto.jpg", "Informes", "Vacía", "basura.tmp", ".oculto"]})
    assert resp.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(resp.get_data())).namelist()
    assert "foto.jpg" in names and "Informes/resumen.md" in names and "Vacía/" in names
    assert not any("basura" in n or "oculto" in n or ".keep" in n for n in names), names  # ocultos, como en la web
    assert client.get("/zip/lectura/").status_code == 200                                 # solo lectura: se descarga
    assert client.get("/zip/home/no-existe").status_code == 404


def test_zip_of_many_files_streams_in_parts(setup):
    app, _client, _token, home, _shared, _ro = setup
    for i in range(30):
        (home / "muchos" / f"{i:02d}.bin").parent.mkdir(exist_ok=True)
        (home / "muchos" / f"{i:02d}.bin").write_bytes(bytes([i]) * 200_000)
    with app.app_context():
        from storageweb.core import storage
        from storageweb.web.context import settings
        from storageweb.db.repositories import users
        from storageweb.web.context import get_db
        root = next(r for r in storage.available_roots(users.get_by_username(get_db(), "ana"), settings())
                    if r["name"] == "home")
        parts = list(files_core.zip_stream(settings(), [(root, "muchos")]))
    assert len(parts) > 3, "se genera por trozos, sin esperar al final"
    zf = zipfile.ZipFile(io.BytesIO(b"".join(parts)))
    assert len([n for n in zf.namelist() if n.endswith(".bin")]) == 30 and zf.read("muchos/07.bin") == bytes([7]) * 200_000


# --------------------------------------------------------------------------- buscar

def test_search_by_name_everywhere_without_accents(setup):
    _app, client, _token, _home, shared, _ro = setup
    (shared / "Año fiscal").mkdir()
    html = client.get("/search?q=ano").get_data(as_text=True)
    assert "año.txt" in html and "Año fiscal" in html and "Equipo" in html
    data = client.get("/search?q=AÑO", headers={"Accept": "application/json"}).get_json()
    assert {(i["root"], i["path"]) for i in data["items"]} == {("home", "Informes/2026/año.txt"), ("equipo", "Año fiscal")}
    assert client.get("/search?q=manual", headers={"Accept": "application/json"}).get_json()["items"][0]["root"] == "lectura"


def test_search_words_scope_and_hidden(setup):
    _app, client, _token, _home, _shared, _ro = setup
    get = lambda **q: client.get("/search", query_string=q, headers={"Accept": "application/json"}).get_json()  # noqa: E731
    assert [i["name"] for i in get(q="resu md")["items"]] == ["resumen.md"]                # todas las palabras
    assert get(q="resu foto")["items"] == []
    assert [i["path"] for i in get(q="txt", root="home", path="Informes")["items"]] == ["Informes/2026/año.txt"]
    assert get(q="basura")["items"] == [] and get(q="oculto")["items"] == []                # ocultos, como en la web
    assert client.get("/search?q=x&root=home&path=../..").status_code == 404
    assert "Buscar archivos" in client.get("/search").get_data(as_text=True)


def test_search_stops_at_the_limits(setup):
    app, _client, _token, home, _shared, _ro = setup
    for i in range(30):
        (home / f"dato-{i}.txt").write_bytes(b"x")
    with app.app_context():
        from storageweb.core import storage
        from storageweb.web.context import settings
        from storageweb.db.repositories import users
        from storageweb.web.context import get_db
        roots = storage.available_roots(users.get_by_username(get_db(), "ana"), settings())
        result = files_core.search(settings(), [(r, "") for r in roots], "dato", limit=10)
        assert len(result.items) == 10 and result.truncated
        result = files_core.search(settings(), [(r, "") for r in roots], "dato", max_folders=1)
        assert result.truncated


# --------------------------------------------------------------------------- espacio

def test_free_space_is_shown_with_its_usage(setup, monkeypatch):
    """El panel de la carpeta muestra el espacio libre del almacenamiento y el % usado (también en JSON)."""
    import shutil
    from collections import namedtuple

    _app, client, _token, _home, _shared, _ro = setup
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(500 * 1024**3, 410 * 1024**3, 90 * 1024**3))
    html = client.get("/f/home/").get_data(as_text=True)
    assert "90.0 GB libres" in html or "90 GB libres" in html or "90,0 GB libres" in html
    assert 'data-percent="82"' in html and "space-warn" in html and "82% usado" in html
    data = client.get("/f/home/", headers={"Accept": "application/json"}).get_json()
    assert data["space"] == {"total": 500 * 1024**3, "free": 90 * 1024**3}
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(100, 97, 3))
    html = client.get("/f/home/").get_data(as_text=True)
    assert "space-danger" in html and "Casi lleno" in html


def test_space_unknown_or_unlimited(setup):
    from storageweb.core import storage

    class Remote:
        unlimited_space = False

        def space(self, rel=""):
            return None

    assert storage.space_of({"backend": Remote()}) is None
    Remote.space = lambda self, rel="": {"unlimited": True}
    assert storage.space_of({"backend": Remote()}) == {"unlimited": True}
    from storageweb.core.backends.s3 import S3Backend
    assert S3Backend.unlimited_space


# --------------------------------------------------------------------------- cuotas (solo avisan)

@pytest.fixture
def quota_app(make_app, tmp_path):
    from storageweb.core import quota
    quota.clear()
    shared = tmp_path / "equipo"
    shared.mkdir()
    (shared / "grande.bin").write_bytes(b"x" * (3 * 1024 * 1024))       # 3 MB de una cuota de 2: superada
    app = make_app({"storage": {"home_quota_mb": 10, "shares": [
        {"name": "equipo", "label": "Equipo", "path": str(shared), "users": ["*"], "quota_mb": 2}]}})
    add_user(app, "ana")
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "ana")
    home = tmp_path / "data" / "homes" / "ana"
    home.mkdir(parents=True, exist_ok=True)
    yield app, client, get_csrf(client, "/f/home/"), home
    quota.clear()


def test_quota_of_personal_and_shared_folders(quota_app):
    from storageweb.core import quota
    _app, client, token, home = quota_app
    (home / "datos.bin").write_bytes(b"x" * (9 * 1024 * 1024 + 512 * 1024))   # 9,5 de 10 MB: aviso
    quota.clear()  # escrito por fuera de la web: la caché no se entera (tarda hasta CACHE_SECONDS)
    html = client.get("/f/home/").get_data(as_text=True)
    assert "Cuota: 9.5 MB de 10.0 MB" in html.replace(",", ".") and "95% de la cuota usada: casi llena." in html
    assert "quota-notice quota-warn" in html
    data = client.get("/f/home/", headers={"Accept": "application/json"}).get_json()
    assert data["quota"] == {"used": 9 * 1024 * 1024 + 512 * 1024, "limit": 10 * 1024 * 1024, "complete": True}
    html = client.get("/f/equipo/").get_data(as_text=True)
    assert "Esta carpeta ha superado su cuota" in html and "quota-notice quota-over" in html
    assert "Cuota superada (150%)" in html


def test_quota_only_warns_and_is_recalculated_after_writing(quota_app):
    _app, client, token, home = quota_app
    assert "quota-notice" not in client.get("/f/home/").get_data(as_text=True)
    for name in ("mucho-1.bin", "mucho-2.bin", "mucho-3.bin"):               # 12 MB de una cuota de 10
        resp = client.post("/upload/home/", data={"files": [(io.BytesIO(b"x" * (4 * 1024 * 1024)), name)]},
                           headers={"X-CSRF-Token": token, "Accept": "application/json"},
                           content_type="multipart/form-data")
        assert resp.get_json()["saved"] == [name]                          # no se bloquea: solo avisa
    assert "quota-notice quota-over" in client.get("/f/home/").get_data(as_text=True)   # sin esperar a la caché
    client.post("/delete/home/mucho-1.bin", data={"_csrf": token})
    client.post("/delete/home/mucho-2.bin", data={"_csrf": token})
    client.post("/delete/home/mucho-3.bin", data={"_csrf": token})
    assert "quota-notice" not in client.get("/f/home/").get_data(as_text=True)


def test_quota_per_user_in_the_admin_and_profile(quota_app):
    from storageweb.db.repositories import users
    from storageweb.web.context import get_db

    app, client, _token, home = quota_app
    (home / "a.bin").write_bytes(b"x" * (1024 * 1024))
    from storageweb.core import quota
    quota.clear()
    assert "Espacio de mi carpeta" in client.get("/profile").get_data(as_text=True)
    admin = app.test_client()
    login(admin, "root")
    token = get_csrf(admin, "/f/home/")
    with app.app_context():
        uid = users.get_by_username(get_db(), "ana")["id"]
    form = {"_csrf": token, "role": "user", "enabled": "on", "display_name": "", "email": "", "home_path": ""}
    html = admin.get(f"/admin/users/{uid}").get_data(as_text=True)
    assert 'name="quota_mb"' in html and "por defecto: 10" in html and "1.0 MB" in html.replace(",", ".")
    admin.post(f"/admin/users/{uid}", data={**form, "quota_mb": "1"})
    with app.app_context():
        assert users.get_by_id(get_db(), uid)["quota_mb"] == 1
    assert "Cuota: 1.0 MB de 1.0 MB" in client.get("/f/home/").get_data(as_text=True).replace(",", ".")
    admin.post(f"/admin/users/{uid}", data={**form, "quota_mb": "0"})       # 0 = sin cuota
    assert "Cuota:" not in client.get("/f/home/").get_data(as_text=True)
    admin.post(f"/admin/users/{uid}", data={**form, "quota_mb": ""})        # vacío = la de por defecto
    with app.app_context():
        assert users.get_by_id(get_db(), uid)["quota_mb"] is None
    resp = admin.post(f"/admin/users/{uid}", data={**form, "quota_mb": "-3"}, follow_redirects=True)
    assert "número entero de MB" in resp.get_data(as_text=True)


def test_quota_of_a_shared_folder_in_its_page(quota_app):
    from storageweb.web.context import settings

    app, _client, _token, _home = quota_app
    admin = app.test_client()
    login(admin, "root")
    html = admin.get("/admin/access/folders/equipo").get_data(as_text=True)
    assert 'name="quota_mb" min="0" value="2"' in html and "Cuota superada" in html and "3.0 MB" in html.replace(",", ".")
    with app.app_context():
        assert settings()["storage"]["shares"][0]["quota_mb"] == 2

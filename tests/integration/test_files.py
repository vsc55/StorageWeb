import io
import os

import pytest

from tests.helpers import add_user, get_csrf, login, visible
from storageweb.web.context import get_db


def upload(client, token, url, files, as_json=True):
    data = {"files": [(io.BytesIO(content), name) for name, content in files]}
    headers = {"X-CSRF-Token": token}
    if as_json:
        headers["Accept"] = "application/json"
    return client.post(url, data=data, headers=headers, content_type="multipart/form-data")


def test_home_created_on_first_access(logged, home):
    client, _ = logged
    assert home.is_dir()
    html = client.get("/f/home/").get_data(as_text=True)
    assert "Mi carpeta" in html and "Carpeta vacía" in html


def test_upload_and_download(logged, home):
    client, token = logged
    resp = upload(client, token, "/upload/home/", [("informe año.txt", b"contenido")])
    assert resp.status_code == 200
    assert resp.get_json() == {"saved": ["informe año.txt"], "errors": []}
    assert (home / "informe año.txt").read_bytes() == b"contenido"

    resp = client.get("/download/home/informe año.txt")
    assert resp.status_code == 200 and resp.data == b"contenido"
    assert "attachment" in resp.headers["Content-Disposition"]


def test_upload_without_csrf_rejected(logged, home):
    client, _ = logged
    resp = upload(client, "malo", "/upload/home/", [("a.txt", b"x")])
    assert resp.status_code == 400
    assert not (home / "a.txt").exists()


def test_upload_form_fallback_redirects(logged, home):
    client, token = logged
    resp = client.post("/upload/home/", data={"files": [(io.BytesIO(b"x"), "a.txt")], "_csrf": token},
                       content_type="multipart/form-data")
    assert resp.status_code == 302
    assert (home / "a.txt").exists()


def test_upload_duplicate_gets_suffix(logged, home):
    client, token = logged
    upload(client, token, "/upload/home/", [("a.txt", b"1")])
    upload(client, token, "/upload/home/", [("a.txt", b"2")])
    assert (home / "a.txt").read_bytes() == b"1"
    assert (home / "a (1).txt").read_bytes() == b"2"


def test_upload_filename_traversal_is_neutralized(logged, home, tmp_path):
    client, token = logged
    upload(client, token, "/upload/home/", [("../../escape.txt", b"x")])
    assert (home / "escape.txt").exists()
    assert not (tmp_path / "data" / "escape.txt").exists()


def test_upload_too_large(logged, home):
    client, token = logged
    resp = upload(client, token, "/upload/home/", [("big.bin", b"x" * (6 * 1024 * 1024))])
    assert resp.status_code == 413
    assert not (home / "big.bin").exists()


def test_no_temp_files_left(logged, home):
    client, token = logged
    upload(client, token, "/upload/home/", [("a.txt", b"x"), ("b.txt", b"y")])
    assert sorted(p.name for p in home.iterdir()) == ["a.txt", "b.txt"]


def test_mkdir_and_nested_upload(logged, home):
    client, token = logged
    client.post("/mkdir/home/", data={"name": "Proyectos", "_csrf": token})
    assert (home / "Proyectos").is_dir()
    upload(client, token, "/upload/home/Proyectos", [("a.bin", b"x")])
    assert (home / "Proyectos" / "a.bin").exists()
    html = client.get("/f/home/Proyectos").get_data(as_text=True)
    assert "a.bin" in html and "Proyectos" in html


def test_mkdir_invalid_or_existing(logged, home):
    client, token = logged
    client.post("/mkdir/home/", data={"name": "x", "_csrf": token})
    html = client.post("/mkdir/home/", data={"name": "x", "_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "Ya existe" in html
    html = client.post("/mkdir/home/", data={"name": "..", "_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "no válido" in html


def test_listing_sorted_and_hidden(logged, home):
    client, _ = logged
    (home / "zeta.txt").write_text("z")
    (home / "Alfa").mkdir()
    (home / ".oculto").write_text("o")
    html = client.get("/f/home/").get_data(as_text=True)
    assert html.index("Alfa") < html.index("zeta.txt")
    assert ".oculto" not in html


def test_rename(logged, home):
    client, token = logged
    (home / "viejo.txt").write_text("x")
    client.post("/rename/home/viejo.txt", data={"name": "nuevo.txt", "_csrf": token})
    assert (home / "nuevo.txt").exists() and not (home / "viejo.txt").exists()


def test_rename_conflict(logged, home):
    client, token = logged
    (home / "a.txt").write_text("a")
    (home / "b.txt").write_text("b")
    html = client.post("/rename/home/a.txt", data={"name": "b.txt", "_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "Ya existe" in html
    assert (home / "b.txt").read_text() == "b"


def test_delete_file_and_folder(logged, home):
    client, token = logged
    (home / "a.txt").write_text("a")
    (home / "dir" / "sub").mkdir(parents=True)
    (home / "dir" / "sub" / "x").write_text("x")
    client.post("/delete/home/a.txt", data={"_csrf": token})
    client.post("/delete/home/dir", data={"_csrf": token})
    assert list(home.iterdir()) == []


def test_cannot_delete_root(logged, home):
    client, token = logged
    assert client.post("/delete/home/", data={"_csrf": token}).status_code in (404, 405)
    assert home.is_dir()


def test_delete_symlink_removes_link_not_target(logged, home):
    client, token = logged
    (home / "real").mkdir()
    (home / "real" / "dato.txt").write_text("x")
    try:
        os.symlink(home / "real", home / "enlace", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("El sistema no permite crear symlinks")
    client.post("/delete/home/enlace", data={"_csrf": token})
    assert not (home / "enlace").exists()
    assert (home / "real" / "dato.txt").exists()


@pytest.mark.parametrize("url", [
    "/download/home/../../config.json",
    "/download/home/..%2F..%2Fconfig.json",
    "/f/home/../../",
    "/download/home/%2e%2e/%2e%2e/config.json",
])
def test_path_traversal(logged, url):
    client, _ = logged
    resp = client.get(url, follow_redirects=True)
    assert resp.status_code == 404


def test_users_are_isolated(app, client, tmp_path):
    add_user(app, "ana")
    add_user(app, "beto")
    login(client, "beto")
    token = get_csrf(client, "/f/home/")
    upload(client, token, "/upload/home/", [("de-beto.txt", b"x")])
    client.post("/logout", data={"_csrf": token})
    login(client, "ana")
    assert "de-beto.txt" not in client.get("/f/home/").get_data(as_text=True)
    assert client.get("/download/home/../beto/de-beto.txt").status_code == 404


def test_custom_home_path(app, client, tmp_path):
    custom = tmp_path / "otra-ruta"
    add_user(app, "ana", home_path=str(custom))
    login(client, "ana")
    client.get("/f/home/")
    assert custom.is_dir()


# --------------------------------------------------------------------------- shares

@pytest.fixture
def shares_app(make_app, tmp_path):
    for name in ("comun", "docs", "rrhh"):
        (tmp_path / name).mkdir()
    (tmp_path / "docs" / "leeme.txt").write_text("hola")
    app = make_app({"storage": {"shares": [
        {"name": "comun", "label": "Común", "path": str(tmp_path / "comun"), "users": ["*"]},
        {"name": "docs", "path": str(tmp_path / "docs"), "read_only": True, "users": ["*"]},
        {"name": "rrhh", "path": str(tmp_path / "rrhh"), "users": ["carla"], "groups": ["rrhh"]},
        {"name": "falta", "path": str(tmp_path / "no-existe"), "users": ["*"]},
    ]}})
    add_user(app, "ana")
    add_user(app, "beto", groups=["rrhh"])
    add_user(app, "carla")
    return app


def test_share_visibility(shares_app):
    client = shares_app.test_client()
    login(client, "ana")
    html = client.get("/f/home/").get_data(as_text=True)
    assert "Común" in html and "/f/docs/" in html and "/f/rrhh/" not in html
    assert client.get("/f/rrhh/").status_code == 404


@pytest.mark.parametrize("user", ["beto", "carla"])
def test_share_by_group_or_user(shares_app, user):
    client = shares_app.test_client()
    login(client, user)
    assert client.get("/f/rrhh/").status_code == 200


def test_share_upload(shares_app, tmp_path):
    client = shares_app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/comun/")
    upload(client, token, "/upload/comun/", [("x.txt", b"x")])
    assert (tmp_path / "comun" / "x.txt").exists()


def test_read_only_share(shares_app, tmp_path):
    client = shares_app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/docs/")
    assert client.get("/download/docs/leeme.txt").data == b"hola"
    assert upload(client, token, "/upload/docs/", [("n.txt", b"x")]).status_code == 403
    assert client.post("/delete/docs/leeme.txt", data={"_csrf": token}).status_code == 403
    assert client.post("/rename/docs/leeme.txt", data={"name": "z", "_csrf": token}).status_code == 403
    assert client.post("/mkdir/docs/", data={"name": "z", "_csrf": token}).status_code == 403
    assert (tmp_path / "docs" / "leeme.txt").exists()
    assert "Subir archivos" not in visible(client.get("/f/docs/").get_data(as_text=True))


def test_missing_share_dir(shares_app):
    client = shares_app.test_client()
    login(client, "ana")
    assert client.get("/f/falta/").status_code == 404


def test_create_shares_option(make_app, tmp_path):
    app = make_app({"storage": {"create_shares": True, "shares": [
        {"name": "nuevo", "path": str(tmp_path / "nuevo"), "users": ["*"]}]}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    assert client.get("/f/nuevo/").status_code == 200
    assert (tmp_path / "nuevo").is_dir()


def test_audit_file_operations(app, logged, home):
    
    client, token = logged
    upload(client, token, "/upload/home/", [("a.txt", b"x")])
    client.get("/download/home/a.txt")
    client.post("/delete/home/a.txt", data={"_csrf": token})
    with app.app_context():
        rows = get_db().execute(
            "SELECT action, target FROM audit_log WHERE action IN ('upload','download','delete') ORDER BY id"
        ).fetchall()
    assert [(r["action"], r["target"]) for r in rows] == [
        ("upload", "home:/a.txt"), ("download", "home:/a.txt"), ("delete", "home:/a.txt")]


# --------------------------------------------------------------------------- layout C: orden, árbol y detalle

def test_sort_by_size_and_date(logged, home):
    import os
    import time

    client, _ = logged
    (home / "grande.bin").write_bytes(b"x" * 3000)
    (home / "medio.bin").write_bytes(b"x" * 2000)
    (home / "pequeno.bin").write_bytes(b"x" * 10)
    (home / "carpeta").mkdir()
    now = time.time()
    os.utime(home / "pequeno.bin", (now, now))
    os.utime(home / "grande.bin", (now - 100, now - 100))
    os.utime(home / "medio.bin", (now - 50, now - 50))

    def order(query):
        html = client.get(f"/f/home/{query}").get_data(as_text=True)
        names = ["carpeta", "grande.bin", "medio.bin", "pequeno.bin"]
        return sorted(names, key=lambda n: html.index(f'data-name="{n}"'))

    assert order("?sort=size&order=desc") == ["carpeta", "grande.bin", "medio.bin", "pequeno.bin"]
    assert order("?sort=size") == ["carpeta", "pequeno.bin", "medio.bin", "grande.bin"]
    assert order("?sort=mtime&order=desc") == ["carpeta", "pequeno.bin", "medio.bin", "grande.bin"]
    assert order("?sort=nada") == ["carpeta", "grande.bin", "medio.bin", "pequeno.bin"]  # valor no válido = nombre
    html = client.get("/f/home/?sort=size&order=desc").get_data(as_text=True)
    assert 'aria-sort="descending"' in html


def test_tree_shows_path_and_subfolders(logged, home):
    client, _ = logged
    (home / "Proyectos" / "2026").mkdir(parents=True)
    (home / "Proyectos" / "Contratos").mkdir()
    html = client.get("/f/home/Proyectos").get_data(as_text=True)
    tree = html.split('class="tree"', 1)[1].split("</aside>", 1)[0]
    assert "Proyectos" in tree and "2026" in tree and "Contratos" in tree
    assert 'class="tree-item level-1 active"' in tree


def test_row_data_for_details_panel(logged, home):
    client, _ = logged
    (home / "informe.zip").write_bytes(b"x" * 1536)
    html = client.get("/f/home/").get_data(as_text=True)
    assert 'data-name="informe.zip"' in html and 'data-dir="0"' in html
    assert 'data-kind="Archivo ZIP"' in html and 'data-size="1,5 KB"' in html
    assert 'data-href="/download/home/informe.zip"' in html


def test_folder_tree_shows_siblings_on_every_level(logged, home):
    """El árbol de la izquierda, como el Explorador: al entrar en una carpeta no desaparecen sus hermanas."""
    import re
    client, _ = logged
    for rel in ("Codigo/src/app", "Codigo/docs", "Prueba/x", "Otra"):
        (home / rel).mkdir(parents=True, exist_ok=True)
    (home / "suelto.txt").write_bytes(b"x")
    html = client.get("/f/home/Codigo/src/").get_data(as_text=True)
    tree = html[html.index('class="tree"'):html.index('class="listing"')]
    names = re.findall(r'level-(\d) ?([a-z-]*)"[^>]*>\s*<svg[^>]*>.*?</svg><span class="tree-name">([^<]+)<', tree, re.S)
    assert [(lvl, name) for lvl, _cls, name in names] == [
        ("1", "Codigo"), ("2", "docs"), ("2", "src"), ("3", "app"), ("1", "Otra"), ("1", "Prueba")]
    states = {name: cls for _lvl, cls, name in names}
    assert states["src"] == "active" and states["Codigo"] == "on-path" and states["Prueba"] == ""
    assert "suelto.txt" not in tree, "solo carpetas"


def test_the_browser_page_loads_the_upload_script_only_where_one_can_upload(make_app):
    """El bloque de scripts no ve los {% set %} del contenido: con can_upload ahí, upload.js no se cargaba nunca."""
    app = make_app({"permissions": {"user": {"upload": True}}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    page = client.get("/f/home/").get_data(as_text=True)
    for script in ("js/app.js", "js/files/upload.js", "js/files/transfer.js", "js/files/listing.js"):
        assert script in page, script
    app = make_app({"permissions": {"user": {"upload": False}}})
    add_user(app, "luis")
    client = app.test_client()
    login(client, "luis")
    page = client.get("/f/home/").get_data(as_text=True)
    assert "js/app.js" in page and "js/files/upload.js" not in page

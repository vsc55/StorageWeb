"""El selector de rutas de la administración (Examinar y autocompletado): qué lista en cada sitio (las carpetas de una
persona, una ubicación, el disco del servidor), que solo lo usan administradores y qué campos lo llevan."""
from __future__ import annotations

from storageweb.core import pathpicker, storage
from storageweb.db.repositories import users
from storageweb.web.context import get_db, settings
from tests.helpers import U, add_user, signed_in


def test_disk_lists_folders_only(tmp_path):
    (tmp_path / "datos" / "a").mkdir(parents=True)
    (tmp_path / "datos" / "b").mkdir()
    (tmp_path / "datos" / "nota.txt").write_text("x", encoding="utf-8")
    got = pathpicker.browse_disk(str(tmp_path / "datos"))
    assert [e["name"] for e in got["entries"]] == ["a", "b"] and all(e["is_dir"] for e in got["entries"])
    assert got["parent"] == str(tmp_path) and got["error"] == ""
    # Una carpeta que aún no existe: la primera que sí, hacia arriba (una carpeta personal nueva)
    assert pathpicker.browse_disk(str(tmp_path / "datos" / "nueva" / "otra"))["path"] == str(tmp_path / "datos")
    assert pathpicker.browse_disk("relativa/x")["error"]                      # en el disco, rutas absolutas
    assert pathpicker.browse_disk("", start=str(tmp_path))["path"] == str(tmp_path)


def test_a_persons_folder_with_files_and_without_hidden(make_app, home):
    app = make_app({"storage": {"hidden": ["secreto"]}})
    add_user(app, "ana")
    (home / "Docs").mkdir(parents=True)
    (home / "Docs" / "plan.md").write_text("x", encoding="utf-8")
    (home / "secreto").mkdir()
    with app.app_context():
        ana = users.get_by_username(get_db(), "ana")
        root = storage.available_roots(ana, settings())[0]
        top = pathpicker.browse_root(settings(), root, "", files=True)
        docs = pathpicker.browse_root(settings(), root, "/Docs/", files=True)
        only_dirs = pathpicker.browse_root(settings(), root, "Docs", files=False)
        assert pathpicker.browse_root(settings(), root, "../fuera")["error"]
        assert pathpicker.browse_root(settings(), root, "secreto")["error"]
        assert pathpicker.browse_location(settings(), "no-existe", "")["error"]
    assert [e["name"] for e in top["entries"]] == ["Docs"] and top["parent"] is None
    assert docs["path"] == "Docs" and docs["parent"] == "" and [e["path"] for e in docs["entries"]] == ["Docs/plan.md"]
    assert only_dirs["entries"] == []


def test_the_route_is_for_administrators(app, admin, home):
    client, token = admin
    h = {"X-CSRF-Token": token}
    add_user(app, "ana")
    (home / "Docs").mkdir(parents=True)
    with app.app_context():
        ana = users.get_by_username(get_db(), "ana")
    got = client.get(f"/admin/browse?scope=root&user={U(ana)}&root=home&files=1", headers=h).get_json()
    assert [e["name"] for e in got["entries"]] == ["Docs"]
    assert client.get("/admin/browse?scope=root&user=nadie&root=home", headers=h).status_code == 404
    assert client.get(f"/admin/browse?scope=root&user={U(ana)}&root=de-otro", headers=h).status_code == 404
    disk = client.get(f"/admin/browse?scope=location&path={home}", headers=h).get_json()   # sin ubicación: el disco
    assert disk["path"] and [e["name"] for e in disk["entries"]] == ["Docs"]
    assert client.get("/admin/browse?scope=otro", headers=h).status_code == 400
    luis, _ = signed_in(app, "luis", csrf_url=None)
    assert luis.get(f"/admin/browse?scope=location&path={home}").status_code == 403


def test_the_path_fields_carry_it(app, admin):
    client, _token = admin
    add_user(app, "ana")
    with app.app_context():
        ana = users.get_by_username(get_db(), "ana")
    for url in (f"/admin/users/{U(ana)}", f"/admin/users/panel?u={U(ana)}", "/admin/users/new",
                "/admin/settings/auto_backups"):
        page = client.get(url).get_data(as_text=True)
        assert "data-browse=" in page and "/static/js/admin/path-picker.js" in page, url
    favorites = client.get(f"/admin/users/{U(ana)}").get_data(as_text=True)
    assert 'data-root-from="select[name=root]"' in favorites and 'data-files="1"' in favorites


def test_never_network_or_device_paths():
    r"""Listar \\equipo\recurso haría que el SERVIDOR se conectara por SMB a ese equipo (con su cuenta: hash NTLM
    para quien lo reciba); \\?\ y \\.\ son rutas de dispositivo de Windows."""
    for path in (r"\\evil\share", "//evil/share", r"\\?\C:\Windows", r"\\.\PhysicalDrive0", r"\/evil", r"/\evil"):
        assert pathpicker.network_path(path), path
        got = pathpicker.browse_disk(path)
        assert got["entries"] == [] and "red" in got["error"], path
        assert pathpicker.browse_disk("", start=path)["entries"] == []           # tampoco como punto de partida
    for path in (r"C:\Windows", "/srv/datos", "D:/x"):
        assert not pathpicker.network_path(path), path
    assert pathpicker.browse_disk("/tmp\x00/x")["error"]                          # caracteres de control


def test_only_from_the_page_itself(app, admin, home):
    """GET, pero recorre carpetas y se conecta a ubicaciones: sin el token CSRF en la cabecera (otra web que hace
    navegar al navegador de un administrador), nada."""
    client, token = admin
    (home / "Docs").mkdir(parents=True)
    url = f"/admin/browse?scope=location&path={home}"
    assert client.get(url).status_code == 403
    assert client.get(url, headers={"X-CSRF-Token": "otro"}).status_code == 403
    assert client.get(url, headers={"X-CSRF-Token": token}).status_code == 200

"""Favoritos de otra persona desde su ficha (Personas → usuario): verlos todos (también los que ya no le sirven),
quitar uno o todos y añadirle uno que exista en una de sus carpetas. Todo auditado; sus archivos no se tocan."""
from __future__ import annotations

from storageweb.db.repositories import favorites as repo
from storageweb.db.repositories import users
from storageweb.web.context import get_db
from tests.helpers import U, add_user, get_user, last_audit


def _ana(app):
    add_user(app, "ana")
    return get_user(app, "ana")


def test_list_remove_and_clear(app, admin, home):
    client, token = admin
    ana = _ana(app)
    (home / "Proyectos").mkdir(parents=True)
    with app.app_context():
        repo.add(get_db(), ana["id"], "home", "Proyectos", True)
        repo.add(get_db(), ana["id"], "home", "notas.txt", False)
        repo.add(get_db(), ana["id"], "compartida-que-ya-no-esta", "x", True)      # sin acceso
    page = client.get(f"/admin/users/{U(ana)}").get_data(as_text=True)
    assert 'id="sec-favorites"' in page and "Proyectos" in page and "notas.txt" in page
    assert "ya sin acceso" in page                                                  # el que ya no le sirve, también
    resp = client.post(f"/admin/users/{U(ana)}/favorites/remove",
                       data={"_csrf": token, "root": "home", "rel": "notas.txt"})
    assert resp.status_code == 302 and resp.location.endswith("#sec-favorites")
    with app.app_context():
        assert [r["rel"] for r in repo.list_for_user(get_db(), ana["id"])] == ["Proyectos", "x"]
    assert last_audit(app, "favorite_removed_by_admin")["detail"] == "home:/notas.txt"
    client.post(f"/admin/users/{U(ana)}/favorites/clear", data={"_csrf": token})
    with app.app_context():
        assert repo.list_for_user(get_db(), ana["id"]) == []
    assert last_audit(app, "favorites_cleared_by_admin")["detail"] == "removed=2"
    assert (home / "Proyectos").is_dir()                                            # los archivos, intactos


def test_add_one_that_exists_in_their_folders(app, admin, home):
    client, token = admin
    ana = _ana(app)
    (home / "Docs" / "Actas").mkdir(parents=True)
    (home / "Docs" / "plan.md").write_text("x", encoding="utf-8")
    url = f"/admin/users/{U(ana)}/favorites/add"
    client.post(url, data={"_csrf": token, "root": "home", "path": "/Docs/Actas/"})
    client.post(url, data={"_csrf": token, "root": "home", "path": "Docs/plan.md"})
    with app.app_context():
        rows = {r["rel"]: bool(r["is_dir"]) for r in repo.list_for_user(get_db(), ana["id"])}
    assert rows == {"Docs/Actas": True, "Docs/plan.md": False}
    assert last_audit(app, "favorite_added_by_admin")["target"] == "ana"
    for path, message in (("No/Existe", "no existe"), ("../root", "no es válida")):
        page = client.post(url, data={"_csrf": token, "root": "home", "path": path},
                           follow_redirects=True).get_data(as_text=True)
        assert message in page, path
    page = client.post(url, data={"_csrf": token, "root": "de-otro", "path": "x"},
                       follow_redirects=True).get_data(as_text=True)
    assert "no es de las de esta persona" in page


def test_only_administrators(app, make_app):
    ana = _ana(app)
    add_user(app, "luis")
    from tests.helpers import login
    client = app.test_client()
    login(client, "luis")
    assert client.post(f"/admin/users/{U(ana)}/favorites/clear").status_code in (302, 400, 403)


def test_the_panel_view_has_a_favorites_tab(app, admin, home):
    client, token = admin
    ana = _ana(app)
    (home / "Docs").mkdir(parents=True)
    with app.app_context():
        repo.add(get_db(), ana["id"], "home", "Docs", True)
    page = client.get(f"/admin/users/panel?u={U(ana)}&tab=favorites").get_data(as_text=True)
    assert "Favoritos (1)" in page and "Docs" in page and 'name="path"' in page
    here = f"/admin/users/panel?u={U(ana)}&tab=favorites"
    resp = client.post(f"/admin/users/{U(ana)}/favorites/remove",
                       data={"_csrf": token, "root": "home", "rel": "Docs", "next": here})
    assert resp.status_code == 302 and resp.location.endswith(here)              # vuelve a la pestaña
    # La carpeta personal: la ayuda va debajo del campo (alineado con el rol de al lado)
    profile = client.get(f"/admin/users/panel?u={U(ana)}").get_data(as_text=True)
    assert "Vacío = la plantilla por defecto." in profile


def test_the_panel_view_has_what_the_full_record_has(app, admin, home):
    """Lo de la ficha también en los paneles: origen, alta y último acceso; la cuota; inicio de sesión y seguridad
    (verificación en dos pasos, sesiones y tokens); y eliminar, volviendo a los paneles."""
    client, token = admin
    ana = _ana(app)
    from storageweb.core import tokens
    with app.app_context():
        tokens.create(get_db(), ana, name="script-de-ana", scope="read", days=0)
    base = f"/admin/users/panel?u={U(ana)}"
    profile = client.get(base).get_data(as_text=True)
    assert "user-facts" in profile and "Local" in profile          # origen, alta y último acceso
    assert 'name="quota_mb"' in profile
    client.post(f"/admin/users/{U(ana)}", data={"_csrf": token, "role": "user", "display_name": "", "email": "",
                                                "home_path": "", "quota_mb": "250", "next": base})
    with app.app_context():
        assert users.get_by_username(get_db(), "ana")["quota_mb"] == 250
    security = client.get(base + "&tab=security").get_data(as_text=True)
    assert "script-de-ana" in security and "Revocar" in security and "user-row" in security
    resp = client.post(f"/admin/users/{U(ana)}/delete", data={"_csrf": token, "next": "/admin/users/panel"})
    assert resp.status_code == 302 and resp.location.endswith("/admin/users/panel")
    with app.app_context():
        assert users.get_by_username(get_db(), "ana") is None

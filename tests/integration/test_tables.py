"""Las tablas que van por páginas se ordenan en el servidor (?sort=&order=, las cabeceras de tables.js): Usuarios y
Auditoría. Las demás se ordenan en el navegador (tests/browser/admin.test.mjs)."""
from __future__ import annotations

import re

from storageweb.db.repositories import audit, users
from storageweb.web.context import get_db
from tests.helpers import add_user, signed_in


def _order(html: str, names) -> list[str]:
    """En qué orden salen ``names`` en la página."""
    found = sorted((html.find(f">{n}<"), n) for n in names if html.find(f">{n}<") != -1)
    return [n for _pos, n in found]


def test_users_are_sorted_by_the_server(app):
    client, _csrf = signed_in(app, "root", role="admin")
    for name, login in (("bea", "2026-01-03T10:00:00+00:00"), ("ana", "2026-03-01T10:00:00+00:00"), ("carla", None)):
        uid = add_user(app, name)
        with app.app_context():
            users.update(get_db(), uid, last_login=login)
    html = client.get("/admin/users").get_data(as_text=True)
    assert 'data-sort-key="user"' in html and 'data-sort-server="last_login"' in html
    assert _order(html, ["ana", "bea", "carla"]) == ["ana", "bea", "carla"]
    html = client.get("/admin/users?sort=user&order=desc").get_data(as_text=True)
    assert _order(html, ["ana", "bea", "carla"]) == ["carla", "bea", "ana"]
    # Por último acceso: el más reciente primero en descendente, y quien nunca entró, al final en los dos sentidos
    html = client.get("/admin/users?sort=last_login&order=desc").get_data(as_text=True)
    assert _order(html, ["ana", "bea", "carla"]) == ["ana", "bea", "carla"]
    html = client.get("/admin/users?sort=last_login&order=asc").get_data(as_text=True)
    assert _order(html, ["ana", "bea", "carla"]) == ["bea", "ana", "carla"]
    assert client.get("/admin/users?sort=password_hash").status_code == 200        # lo que no es una columna, ignorado


def test_the_audit_log_is_sorted_by_the_server(app):
    client, _csrf = signed_in(app, "root", role="admin")
    with app.app_context():
        for user, action in (("zoe", "download"), ("alba", "upload"), ("marta", "user_deleted")):
            audit.log(get_db(), action, "x", username=user)
    html = client.get("/admin/audit?sort=user&order=asc").get_data(as_text=True)
    assert _order(html, ["alba", "marta", "zoe"]) == ["alba", "marta", "zoe"]
    assert 'data-sort-key="user"' in html and 'data-sort-order="asc"' in html
    html = client.get("/admin/audit").get_data(as_text=True)                   # de serie: lo último primero
    assert _order(html, ["alba", "marta", "zoe"]) == ["marta", "alba", "zoe"]
    # Por nivel, por gravedad (warning antes que info en descendente), no por orden alfabético
    html = client.get("/admin/audit?sort=level&order=desc").get_data(as_text=True)
    levels = re.findall(r'class="level level-(\w+)"', html)
    assert levels and levels == sorted(levels, key=lambda lv: ["debug", "info", "warning", "error", "critical"].index(lv),
                                       reverse=True)


def test_every_page_loads_the_table_script(app):
    client, _csrf = signed_in(app, "root", role="admin")
    for url in ("/admin/groups/list", "/admin/settings/system", "/f/home/"):
        assert "/static/js/tables.js" in client.get(url).get_data(as_text=True), url
    assert "data-plain" in client.get("/f/home/").get_data(as_text=True)          # el explorador ordena a su manera

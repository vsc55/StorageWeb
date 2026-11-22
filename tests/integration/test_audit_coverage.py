"""Que todo quede en la auditoría y con su nivel: favoritos, listar y buscar, preferencias, accesos denegados, CSRF,
cuota llena; el mínimo que se guarda (audit.min_level), el filtro por nivel de la página y el CSV."""
from __future__ import annotations

from storageweb import audit_levels
from storageweb.db.repositories import audit
from storageweb.web.context import get_db

from tests.helpers import signed_in


def _events(app, **filters):
    with app.app_context():
        return [(r["action"], r["level"], r["target"], r["detail"]) for r in audit.recent(get_db(), 200, **filters)]


def _actions(app):
    return [e[0] for e in _events(app)]


def test_everything_is_recorded_with_its_level(app, logged, home):
    client, csrf = logged
    (home / "Docs").mkdir(parents=True)
    client.post("/favorites", data={"_csrf": csrf, "root": "home", "path": "Docs"}, headers={"Accept": "application/json"})
    client.post("/favorites", data={"_csrf": csrf, "root": "home", "path": "Docs"}, headers={"Accept": "application/json"})
    client.post("/favorites", data={"_csrf": csrf, "action": "remove", "root": "home", "path": "Docs"},
                headers={"Accept": "application/json"})
    client.get("/f/home/Docs")
    client.get("/search?q=informe")
    client.post("/theme", data={"_csrf": csrf, "theme": "dark", "next": "/"})
    client.post("/mkdir/home/", data={"name": "sin-token"})                   # sin CSRF
    client.get("/admin/")                                                       # ana no es administradora
    events = _events(app)

    def has(action, level, target=None, detail=None):
        return any(a == action and lv == level and (target is None or t == target)
                   and (detail is None or detail in (d or "")) for a, lv, t, d in events)
    assert has("favorite_added", "debug", "home:/Docs")
    assert has("favorite_removed", "debug", "home:/Docs") and has("favorite_removed", "debug", "home:/Docs", "list")
    assert has("folder_listed", "debug", "home:/Docs")
    assert has("search", "debug", "*:/", "informe")
    assert has("preference_changed", "debug", None, "theme=dark")
    assert has("csrf_rejected", "warning", "/mkdir/home/")
    assert has("access_denied", "warning", "/admin/")


def test_quota_exceeded_is_a_warning(make_app, home):
    app = make_app({"storage": {"home_quota_mb": 1}})
    client, csrf = signed_in(app, "ana")
    import io
    client.post("/upload/home/", data={"_csrf": csrf, "files": (io.BytesIO(b"x" * (2 * 1024 * 1024)), "grande.bin")},
                content_type="multipart/form-data")
    assert ("quota_exceeded", "warning", "home:/grande.bin", str(2 * 1024 * 1024)) in _events(app)


def test_min_level_and_audit_page(make_app, home):
    app = make_app({"audit": {"min_level": "info"}})
    client, _ = signed_in(app, "root", role="admin", csrf_url=None)
    try:
        client.get("/f/home/")                                                  # debug: no se guarda
        assert "folder_listed" not in _actions(app) and "login" in _actions(app)
    finally:
        audit_levels.configure("debug")
    with app.app_context():
        audit.log(get_db(), "backup_failed", None, username="system", detail="disco lleno")
        audit.log(get_db(), "login_blocked", "ana", ip="192.0.2.9")
    page = client.get("/admin/audit?level=error").get_data(as_text=True)
    assert "backup_failed" in page and "login_blocked" in page and "<code>login</code>" not in page
    assert 'class="level level-critical"' in page and "Crítico" in page
    csv_text = client.get("/admin/audit/export.csv?level=critical").get_data(as_text=True)
    assert csv_text.lstrip("﻿").splitlines()[0].startswith("ts,level,username,action")   # el CSV lleva BOM
    assert "critical" in csv_text and "backup_failed" not in csv_text

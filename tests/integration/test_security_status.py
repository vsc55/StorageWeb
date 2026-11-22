"""Seguridad → Estado de la seguridad: el tablero, la lista de comprobación (core/posture.py), las vulnerabilidades de
las bibliotecas con su comprobación automática (security.dependency_check_hours) y que nada de eso sale a internet
sin pedirlo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from storageweb.core import advisories, maintenance, posture
from storageweb.db.repositories import ip_rules, users
from storageweb.web.context import get_db
from tests.helpers import add_user, stored_settings, signed_in, last_audit


def _result(total=0, worst=""):
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "checked": 1, "behind": 0,
            "vulns_ok": True, "vulns_error": "", "vuln_asked": 1, "vuln_total": total, "vuln_packages": int(bool(total)),
            "worst": worst, "rows": []}


def test_the_dashboard_and_the_checklist(app, admin):
    client, _token = admin
    with app.app_context():
        ip_rules.add(get_db(), "ban", "203.0.113.7", reason="pruebas", automatic=True)
        from storageweb.db.repositories import audit
        audit.log(get_db(), "login_failed", username="nadie", ip="203.0.113.7")
        audit.log(get_db(), "login_blocked", username="nadie", ip="203.0.113.7")
    page = client.get("/admin/settings/security_status").get_data(as_text=True)
    for text in ("Vulnerabilidades conocidas", "IPs bloqueadas", "Intentos fallidos (24 h)", "Sesiones abiertas",
                 "Tokens de API vigentes", "Lista de comprobación", "Últimos sucesos de seguridad", "login_blocked",
                 "203.0.113.7", "/static/js/admin/sortable.js", "/admin/settings/vulnerabilities"):
        assert text in page, text
    assert 'name="dependency_check_hours"' not in page                     # el tablero es solo de lectura
    vuln = client.get("/admin/settings/vulnerabilities").get_data(as_text=True)
    for text in ("Comprobación automática", 'name="dependency_check_hours"', 'id="advisories"',
                 "/static/js/admin/advisories.js", "/static/js/admin/sortable.js"):
        assert text in vuln, text
    # root es administrador con contraseña y sin verificación en dos pasos, y la política no la exige: a corregir
    assert "Verificación en dos pasos de los administradores" in page and "root" in page
    assert "posture-bad" in page
    # Información solo enlaza: la comprobación vive aquí
    info = client.get("/admin/settings/system").get_data(as_text=True)
    assert "/admin/settings/vulnerabilities" in info and 'id="advisories-form"' not in info


def test_posture_checks(app, make_app):
    app = make_app({"security": {"mfa_required": "admins", "ipban_enabled": False, "password_check": False,
                                 "webdav_passwords": True}})
    add_user(app, "root", role="admin")
    with app.app_context():
        conn = get_db()
        from storageweb.web.context import settings
        cfg = settings()
        ctx = posture.Context(conn, cfg, app.config["SW"], {}, {"notes": []}, secrets_key=False)
        rows = {r["key"]: r for r in posture.collect(ctx)}
    assert rows["admins_mfa"]["state"] == "warn"          # la política se la pedirá: a revisar, no a corregir
    assert rows["guessing"]["state"] == "warn" and rows["passwords"]["state"] == "warn"
    assert rows["webdav"]["state"] == "warn" and rows["secrets"]["state"] == "bad"
    assert rows["backups"]["state"] == "warn"             # sin copias automáticas
    assert rows["libraries"]["state"] == "warn" and "Nunca se ha comprobado" in rows["libraries"]["detail"]
    ordered = [r["state"] for r in posture.collect(ctx)]
    assert ordered == sorted(ordered, key=posture.STATES.index)          # lo grave, arriba
    with app.app_context():
        maintenance.put_state(get_db(), advisories.STATE_KEY, _result(3, "critical"))
        ctx = posture.Context(get_db(), settings(), app.config["SW"], maintenance.state(get_db()), {"notes": []}, True)
        libraries = {r["key"]: r for r in posture.collect(ctx)}["libraries"]
    assert libraries["state"] == "bad" and "3 vulnerabilidades" in libraries["detail"]


def test_the_automatic_check_setting_and_task(app, admin, monkeypatch):
    client, token = admin
    resp = client.post("/admin/settings/vulnerabilities", data={"_csrf": token, "dependency_check_hours": "12"})
    assert resp.status_code in (200, 302)
    assert stored_settings(app)["security"]["dependency_check_hours"] == 12
    bad = client.post("/admin/settings/vulnerabilities", data={"_csrf": token, "dependency_check_hours": "9999"})
    assert "security.dependency_check_hours" in bad.get_data(as_text=True)
    calls = []

    def fake_check(rows, timeout=advisories.TIMEOUT, progress=None):
        calls.append(len(rows))
        return _result()

    monkeypatch.setattr(advisories, "check", fake_check)
    from storageweb.web.context import settings
    with app.app_context():
        cfg = settings()
        assert "dependency_check" in maintenance.run_due(get_db(), cfg)
        assert calls and maintenance.state(get_db())[advisories.STATE_KEY]["vulns_ok"]
        assert last_audit(app, "dependencies_checked")["username"] == "system"
        assert "dependency_check" not in maintenance.run_due(get_db(), cfg)       # hasta dentro de 12 horas, no
        # Si alguien la tiene en marcha, la automática no empieza otra
        state = maintenance.state(get_db())
        state.pop("dependency_check")
        from storageweb.db.repositories import settings as settings_repo
        settings_repo.put(get_db(), maintenance.STATE_KEY, state, "system")
        assert advisories.try_start("root")
        try:
            maintenance.run_due(get_db(), cfg)
            assert len(calls) == 1
        finally:
            advisories.run_job([], cfg["database"], "root")          # la suelta


def test_once_a_day_by_default_and_off_in_the_tests(app):
    from storageweb.settings import DEFAULTS
    from storageweb.web.context import settings
    assert DEFAULTS["security"]["dependency_check_hours"] == 24
    with app.app_context():
        assert settings()["security"]["dependency_check_hours"] == 0        # conftest: los tests no salen
        assert "dependency_check" not in maintenance.run_due(get_db(), settings())


def test_only_administrators(app, make_app):
    client, _ = signed_in(app, "ana", csrf_url=None)
    assert client.get("/admin/settings/security_status").status_code == 403
    assert client.get("/admin/settings/vulnerabilities").status_code == 403
    assert client.get("/admin/settings/system/advisories/status").status_code == 403

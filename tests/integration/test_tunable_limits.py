"""Límites que eran fijos en el código y ahora son ajustes: longitud mínima de la contraseña, caducidad y aviso del
secreto de Entra ID, búsqueda, subidas abandonadas, aviso de cuota, tokens sin usar y la espera de las ubicaciones
remotas. De cada uno: el valor de serie, sus límites, la página que lo guarda y que el código lo usa."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from storageweb.core import quota
from storageweb.db.repositories import users
from storageweb.providers import local
from storageweb.settings import ConfigError, DEFAULTS
from storageweb.settings.location_types import Option
from storageweb.web.context import get_db
from tests.helpers import PASSWORD, add_user, get_csrf, stored_settings, signed_in


def test_defaults_keep_the_old_values():
    st, sec = DEFAULTS["storage"], DEFAULTS["security"]
    assert (st["search_max_results"], st["search_seconds"], st["search_max_folders"]) == (200, 8, 20000)
    assert st["upload_stale_hours"] == 24 and st["quota_warn_percent"] == 90
    assert sec["password_min_length"] == 10 and sec["api_token_unused_days"] == 90
    assert DEFAULTS["auth"]["entra"]["secret_months"] == 24 and DEFAULTS["auth"]["entra"]["secret_warn_days"] == 30


@pytest.mark.parametrize("overrides, field", [
    ({"security": {"password_min_length": 9}}, "security.password_min_length"),       # nunca menos de 10
    ({"security": {"password_min_length": 129}}, "security.password_min_length"),
    ({"storage": {"quota_warn_percent": 100}}, "storage.quota_warn_percent"),
    ({"storage": {"search_seconds": 0}}, "storage.search_seconds"),
    ({"storage": {"search_max_results": "muchos"}}, "storage.search_max_results"),
    ({"storage": {"upload_stale_hours": 721}}, "storage.upload_stale_hours"),
    ({"security": {"api_token_unused_days": -1}}, "security.api_token_unused_days"),
    ({"auth": {"entra": {"secret_months": 25}}}, "auth.entra.secret_months"),
    ({"auth": {"entra": {"secret_warn_days": 0}}}, "auth.entra.secret_warn_days"),
])
def test_out_of_range_is_refused(write_config, overrides, field):
    from storageweb.settings import load_config
    with pytest.raises(ConfigError) as err:
        load_config(str(write_config(overrides)))
    assert err.value.field == field


def test_password_min_length(make_app):
    with pytest.raises(ValueError, match="al menos 14"):
        local.validate_password("caballo-grapa", **local.rules({"security": {"password_min_length": 14,
                                                                            "password_check": True}}))
    with pytest.raises(ValueError, match="al menos 10"):
        local.validate_password("corta-ya", min_length=4)                    # por debajo de 10, nunca
    app = make_app({"security": {"password_min_length": 20}})
    client, _ = signed_in(app, "ana", csrf_url=None)
    page = client.get("/profile/security").get_data(as_text=True)
    assert 'minlength="20"' in page and 'minlength="10"' not in page
    token = get_csrf(client, "/profile/security")
    resp = client.post("/profile/password", data={"_csrf": token, "current_password": PASSWORD,
                                                  "new_password": "caballo-grapa-1", "repeat_password": "caballo-grapa-1"},
                       follow_redirects=True)
    assert "al menos 20" in resp.get_data(as_text=True)


def test_entra_secret_lifetime_and_warning(monkeypatch):
    from storageweb.providers.entra import register as er
    from storageweb.providers.entra.method import EntraMethod
    sent = {}

    def fake_graph(method, path, token, body=None):
        if path.endswith("/addPassword"):
            sent["end"] = body["passwordCredential"]["endDateTime"]
            return {"secretText": "s", "endDateTime": sent["end"]}
        return {"value": [{"id": "obj", "displayName": "X"}]}

    monkeypatch.setattr(er, "_graph", fake_graph)
    er.rotate_secret("tok", "c1", secret_months=6)
    days = (datetime.fromisoformat(sent["end"]) - datetime.now(timezone.utc)).days
    assert 178 <= days <= 180                                                  # 6 meses, no 24
    soon = (datetime.now(timezone.utc) + timedelta(days=45)).isoformat(timespec="seconds")
    method = EntraMethod()
    section = {**DEFAULTS["auth"]["entra"], "client_id": "c1", "secret_expires": soon}
    assert method.notices({**section, "secret_warn_days": 30}) == []
    assert [n.key for n in method.notices({**section, "secret_warn_days": 60})] == ["secret_expiring"]


def test_search_stops_at_the_configured_results(make_app, home):
    app = make_app({"storage": {"search_max_results": 10}})
    client, _ = signed_in(app, "ana", csrf_url=None)
    home.mkdir(parents=True, exist_ok=True)
    for i in range(15):
        (home / f"informe-{i:02d}.txt").write_text("x", encoding="utf-8")
    data = client.get("/search?q=informe", headers={"Accept": "application/json"}).get_json()
    assert len(data["items"]) == 10 and data["truncated"]


def test_quota_warning_threshold(monkeypatch):
    monkeypatch.setattr(quota, "usage", lambda root, **kw: (80 * quota.MB, True))
    root = {"quota_mb": 100, "where": "x"}
    try:
        quota.configure(60, 90)
        assert quota.status(root)["level"] == "ok"
        quota.configure(60, 75)
        assert quota.status(root)["level"] == "warn"
    finally:
        quota.configure(60, quota.WARN_PERCENT)


def test_unused_tokens_warning_can_be_tuned_or_turned_off(make_app):
    from storageweb.core import alerts, tokens
    from storageweb.web.context import settings
    for days, expected in ((0, False), (3650, False), (30, True)):
        app = make_app({"security": {"api_token_unused_days": days}})
        add_user(app, f"u{days}")
        with app.app_context():
            user = users.get_by_username(get_db(), f"u{days}")
            _plain, token_id = tokens.create(get_db(), user, name="viejo", scope="read", days=0)
            old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(timespec="seconds")
            get_db().execute("UPDATE api_tokens SET created_at = ? WHERE id = ?", (old, token_id))
            get_db().commit()
            found = [a for a in alerts.collect(settings(), app.config["SW"], {}) if a["key"] == "tokens_unused"]
        assert bool(found) is expected, days


def test_upload_cleanup_uses_the_setting(make_app, monkeypatch):
    from storageweb.web.api import uploads as api
    asked = []
    monkeypatch.setattr(api.repo, "stale", lambda conn, hours: asked.append(hours) or [])
    app = make_app({"storage": {"upload_stale_hours": 72}})
    with app.test_request_context():
        api._cleanup_stale()
    assert asked == [72]


def test_location_timeout_option():
    opt = Option("timeout", "x", "doc", kind="seconds", default=30)
    assert opt.normalize("", "U") == 30 and opt.normalize("120", "U") == 120
    for bad in ("0", "601", "rápido"):
        with pytest.raises(ConfigError):
            opt.normalize(bad, "U")
    from storageweb.core.backends.webdav import WebDAVClient
    assert WebDAVClient({"url": "https://x/", "timeout": 90}).timeout == 90
    assert WebDAVClient({"url": "https://x/"}).timeout == 30


def test_settings_pages_save_them(app, admin):
    client, token = admin
    page = client.get("/admin/settings/files").get_data(as_text=True)
    assert 'name="search_seconds"' in page and 'name="upload_stale_hours"' in page
    client.post("/admin/settings/files", data={"_csrf": token, "max_file_size_mb": "0", "page_size": "200",
                                               "listing_mode": "scroll", "hidden": "", "upload_stale_hours": "48",
                                               "search_max_results": "500", "search_seconds": "20",
                                               "search_max_folders": "50000"})
    client.post("/admin/settings/quotas", data={"_csrf": token, "home_quota_mb": "0", "quota_enforce": "on",
                                                "quota_refresh_minutes": "60", "quota_warn_percent": "80"})
    client.post("/admin/settings/clients", data={"_csrf": token, "api_tokens": "on", "api_token_max_days": "0",
                                                 "api_token_unused_days": "0", "webdav": "on"})
    stored = stored_settings(app)
    assert stored["storage"]["upload_stale_hours"] == 48 and stored["storage"]["search_seconds"] == 20
    assert stored["storage"]["search_max_results"] == 500 and stored["storage"]["quota_warn_percent"] == 80
    assert stored["security"]["api_token_unused_days"] == 0
    page = client.get("/admin/settings/auth").get_data(as_text=True)
    assert 'name="password_min_length"' not in page and 'name="entra_secret_months"' in page
    assert 'name="password_min_length"' in client.get("/admin/settings/passwords").get_data(as_text=True)

"""Perfil de usuario, tema claro/oscuro y cambio de contraseña."""
import pytest

from storageweb.db.repositories import audit, users
from storageweb.web.context import get_db
from tests.helpers import PASSWORD, add_user, get_csrf, login


def _user(app, username):
    with app.app_context():
        return users.get_by_username(get_db(), username)


def _actions(app):
    with app.app_context():
        return [r["action"] for r in audit.recent(get_db(), 20)]


# --------------------------------------------------------------------------- tema

def test_default_theme_is_system(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'data-theme="system"' in html and 'content="light dark"' in html


def test_theme_anonymous_survives_login(app, client):
    add_user(app, "ana")
    token = get_csrf(client)
    resp = client.post("/theme", data={"_csrf": token, "theme": "dark", "next": "/login"})
    assert resp.status_code == 302 and resp.location == "/login"
    assert 'data-theme="dark"' in client.get("/login").get_data(as_text=True)
    login(client, "ana")
    assert 'data-theme="dark"' in client.get("/f/home/").get_data(as_text=True)


def test_theme_saved_for_user(app, logged):
    client, token = logged
    client.post("/theme", data={"_csrf": token, "theme": "light", "next": "/f/home/"})
    assert _user(app, "ana")["theme"] == "light"
    other = app.test_client()
    login(other, "ana")
    assert 'data-theme="light"' in other.get("/f/home/").get_data(as_text=True)


def test_theme_rejects_unknown_and_requires_csrf(logged, client):
    c, token = logged
    c.post("/theme", data={"_csrf": token, "theme": "rosa", "next": "/f/home/"})
    assert 'data-theme="system"' in c.get("/f/home/").get_data(as_text=True)
    assert client.post("/theme", data={"theme": "dark"}).status_code == 400


# --------------------------------------------------------------------------- menú y perfil

def test_account_menu(logged):
    client, _ = logged
    html = client.get("/f/home/").get_data(as_text=True)
    assert 'class="account-menu"' in html and 'href="/profile"' in html
    assert 'action="/theme"' in html and 'action="/locale"' in html


def test_profile_requires_login(client):
    assert "/login" in client.get("/profile").location


def test_profile_update_local_user(app, logged):
    client, token = logged
    resp = client.post("/profile", data={"_csrf": token, "display_name": "Ana María", "email": "ana@x.com",
                                         "locale": "en", "theme": "dark"})
    assert resp.status_code == 302
    u = _user(app, "ana")
    assert (u["display_name"], u["email"], u["locale"], u["theme"]) == ("Ana María", "ana@x.com", "en", "dark")
    html = client.get("/profile").get_data(as_text=True)
    assert '<html lang="en" data-theme="dark">' in html and "Ana María" in html
    assert "profile_updated" in _actions(app)


def test_profile_browser_language_clears_preference(app, logged):
    client, token = logged
    client.post("/profile", data={"_csrf": token, "locale": "en", "theme": "system"})
    client.post("/profile", data={"_csrf": token, "locale": "", "theme": "system"})
    assert _user(app, "ana")["locale"] is None


def test_profile_entra_user_cannot_change_name(app, client):
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="o1", display_name="Juan")
    from storageweb.db.repositories import sessions
    from storageweb.web.context import get_db
    juan = _user(app, "juan@contoso.com")
    with app.app_context():                             # como un inicio de sesión con Microsoft: sesión registrada
        sessions.create(get_db(), "sesion-juan", juan["id"], "127.0.0.1", "pruebas")
    with client.session_transaction() as sess:
        sess["uid"], sess["sid"], sess["src"] = juan["id"], "sesion-juan", "entra"
    html = client.get("/profile").get_data(as_text=True)
    assert "readonly" in html and 'id="password"' not in html
    token = get_csrf(client, "/profile")
    client.post("/profile", data={"_csrf": token, "display_name": "Otro", "theme": "dark"})
    u = _user(app, "juan@contoso.com")
    assert u["display_name"] == "Juan" and u["theme"] == "dark"
    assert client.post("/profile/password", data={"_csrf": token, "current_password": "x",
                                                  "new_password": "y", "repeat_password": "y"}).status_code == 403


# --------------------------------------------------------------------------- contraseña

@pytest.mark.parametrize("current, new, repeat, message", [
    ("mala-contraseña", "nueva-contraseña-1", "nueva-contraseña-1", "no es correcta"),
    (PASSWORD, "nueva-contraseña-1", "otra-cosa-distinta", "no coinciden"),
    (PASSWORD, PASSWORD, PASSWORD, "distinta de la actual"),
    (PASSWORD, "corta", "corta", "al menos"),
])
def test_change_password_errors(app, logged, current, new, repeat, message):
    client, token = logged
    resp = client.post("/profile/password", data={"_csrf": token, "current_password": current,
                                                  "new_password": new, "repeat_password": repeat},
                       follow_redirects=True)
    assert message in resp.get_data(as_text=True)
    assert login(app.test_client(), "ana").status_code == 302  # la contraseña no ha cambiado


def test_change_password_ok(app, logged):
    client, token = logged
    resp = client.post("/profile/password", data={"_csrf": token, "current_password": PASSWORD,
                                                  "new_password": "nueva-contraseña-1",
                                                  "repeat_password": "nueva-contraseña-1"})
    assert resp.status_code == 302 and resp.location.endswith("/profile#password")
    assert login(app.test_client(), "ana", "nueva-contraseña-1").status_code == 302
    assert "password_changed" in _actions(app)


def test_failed_password_change_audited(app, logged):
    client, token = logged
    client.post("/profile/password", data={"_csrf": token, "current_password": "mala",
                                           "new_password": "nueva-contraseña-1", "repeat_password": "nueva-contraseña-1"})
    assert "password_change_failed" in _actions(app)

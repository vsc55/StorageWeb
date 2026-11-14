"""Sesiones en el servidor y tokens de API personales."""
import io
import re

import pytest

from storageweb.db.repositories import sessions, users
from storageweb.web.context import get_db
from tests.helpers import PASSWORD, add_user, get_csrf, login


def _sessions(app, username=None):
    with app.app_context():
        rows = sessions.list_all(get_db())
    return [r for r in rows if username is None or r["username"] == username]


# --------------------------------------------------------------------------- sesiones

def test_login_registers_and_logout_removes_session(app, client):
    add_user(app, "ana")
    login(client, "ana")
    rows = _sessions(app, "ana")
    assert len(rows) == 1 and rows[0]["ip"] == "127.0.0.1"
    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    assert _sessions(app, "ana") == []


def test_admin_closes_a_session(app, admin):
    client, token = admin
    add_user(app, "ana")
    ana = app.test_client()
    login(ana, "ana")
    assert ana.get("/f/home/").status_code == 200
    html = client.get("/admin/settings/sessions").get_data(as_text=True)
    assert "ana" in html and "Sesiones abiertas" in html
    sid = _sessions(app, "ana")[0]["id"]
    client.post(f"/admin/settings/sessions/{sid}/close", data={"_csrf": token})
    assert ana.get("/f/home/").status_code == 302                     # fuera en la siguiente petición


def test_close_all_sessions_of_user_and_disable(app, admin):
    client, token = admin
    uid = add_user(app, "ana")
    a1, a2 = app.test_client(), app.test_client()
    login(a1, "ana")
    login(a2, "ana")
    assert len(_sessions(app, "ana")) == 2
    client.post(f"/admin/settings/sessions/user/{uid}/close", data={"_csrf": token})
    assert _sessions(app, "ana") == [] and a1.get("/f/home/").status_code == 302
    login(a1, "ana")
    client.post(f"/admin/users/{uid}/status", data={"_csrf": token, "enabled": "0"})
    assert _sessions(app, "ana") == []


def test_profile_sessions_and_password_change(app, client):
    add_user(app, "ana")
    other = app.test_client()
    login(other, "ana")
    login(client, "ana")
    html = client.get("/profile").get_data(as_text=True)
    assert "Mis sesiones" in html and "esta" in html
    token = get_csrf(client, "/profile")
    client.post("/profile/password", data={"_csrf": token, "current_password": PASSWORD,
                                           "new_password": "otra-clave-larga", "repeat_password": "otra-clave-larga"})
    assert other.get("/f/home/").status_code == 302 and client.get("/f/home/").status_code == 200
    assert len(_sessions(app, "ana")) == 1


def test_legacy_session_without_id_is_adopted(app, client):
    uid = add_user(app, "ana")
    with client.session_transaction() as s:
        s["uid"] = uid
        s["src"] = "local"
    assert client.get("/f/home/").status_code == 200
    assert len(_sessions(app, "ana")) == 1


# --------------------------------------------------------------------------- tokens de API

@pytest.fixture
def user_token(app, client):
    """Crea un token desde el perfil y lo devuelve en claro (solo se muestra una vez)."""
    def _make(scope="read"):
        if not _exists(app, "ana"):
            add_user(app, "ana")
        login(client, "ana")
        csrf = get_csrf(client, "/profile")
        client.post("/profile/tokens", data={"_csrf": csrf, "name": f"script-{scope}", "scope": scope, "days": "30"})
        found = re.search(r'value="(sw_[A-Za-z0-9_\-]+)"', client.get("/profile").get_data(as_text=True))
        assert found
        return found.group(1)
    return _make


def _exists(app, name):
    with app.app_context():
        return users.get_by_username(get_db(), name) is not None


def _bearer(plain):
    return {"Authorization": f"Bearer {plain}"}


def test_token_shown_once_and_lists_json(app, client, user_token, tmp_path):
    plain = user_token("read")
    html = client.get("/profile").get_data(as_text=True)
    assert plain not in html and "script-read" in html                 # ya no se vuelve a mostrar
    api = app.test_client()
    resp = api.get("/f/home/", headers=_bearer(plain))
    data = resp.get_json()
    assert resp.status_code == 200 and data["root"] == "home" and data["permissions"] == ["download"]


def test_read_token_downloads_but_cannot_upload(app, client, user_token, home):
    plain = user_token("read")
    home.mkdir(parents=True, exist_ok=True)
    (home / "a.txt").write_text("hola", encoding="utf-8")
    api = app.test_client()
    assert api.get("/download/home/a.txt", headers=_bearer(plain)).data == b"hola"
    resp = api.post("/upload/home/", headers=_bearer(plain), data={"files": (io.BytesIO(b"x"), "b.txt")})
    assert resp.status_code == 403


def test_write_token_uploads_without_csrf(app, client, user_token, home):
    plain = user_token("write")
    api = app.test_client()
    resp = api.post("/upload/home/", headers={**_bearer(plain), "Accept": "application/json"},
                    data={"files": (io.BytesIO(b"datos"), "nuevo.txt")})
    assert resp.status_code == 200 and resp.get_json()["saved"] == ["nuevo.txt"]
    assert (home / "nuevo.txt").read_bytes() == b"datos"


def test_token_cannot_reach_admin_or_profile(app, client, user_token):
    plain = user_token("write")
    api = app.test_client()
    assert api.get("/profile", headers=_bearer(plain)).status_code == 403
    assert api.get("/admin/users", headers=_bearer(plain)).status_code == 403


def test_bad_token_and_disabled_tokens(app, make_app, client, user_token):
    plain = user_token("read")
    api = app.test_client()
    assert api.get("/f/home/", headers=_bearer("sw_falso")).status_code == 401
    app2 = make_app({"security": {"api_tokens": False}})
    assert app2.test_client().get("/f/home/", headers=_bearer(plain)).status_code == 401


def test_revoke_token(app, client, user_token):
    plain = user_token("read")
    html = client.get("/profile").get_data(as_text=True)
    token_id = re.search(r'/profile/tokens/(\d+)/delete', html).group(1)
    client.post(f"/profile/tokens/{token_id}/delete", data={"_csrf": get_csrf(client, "/profile")})
    assert app.test_client().get("/f/home/", headers=_bearer(plain)).status_code == 401


def test_settings_sessions_overview_close_all(app, admin):
    from storageweb.core import tokens

    client, token = admin
    uid = add_user(app, "beto")
    beto = app.test_client()
    login(beto, "beto")
    with app.app_context():
        tokens.create(get_db(), users.get_by_id(get_db(), uid), name="script-beto", scope="read", days=30)
    html = client.get("/admin/settings/sessions").get_data(as_text=True)
    assert "beto" in html and "script-beto" in html and "Cerrar todas menos la mía" in html
    client.post("/admin/settings/sessions/close-all", data={"_csrf": token})
    assert beto.get("/f/home/").status_code == 302 and client.get("/f/home/").status_code == 200
    assert {r["username"] for r in _sessions(app)} == {"root"}


def test_close_selected_sessions(app, admin):
    client, token = admin
    for name in ("beto", "carla"):
        add_user(app, name)
        login(app.test_client(), name)
    beto_sid = _sessions(app, "beto")[0]["id"]
    own_sid = _sessions(app, "root")[0]["id"]
    html = client.get("/admin/settings/sessions").get_data(as_text=True)
    assert f'name="sids" value="{beto_sid}"' in html and f'name="sids" value="{own_sid}"' not in html
    # La propia nunca se cierra aunque llegue en la lista
    client.post("/admin/settings/sessions/close-selected", data={"_csrf": token, "sids": [beto_sid, own_sid]})
    assert {r["username"] for r in _sessions(app)} == {"root", "carla"}
    html = client.post("/admin/settings/sessions/close-selected", data={"_csrf": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "Selecciona al menos una sesión." in html


def test_close_idle_sessions(app, admin):
    client, token = admin
    add_user(app, "beto")
    login(app.test_client(), "beto")
    with app.app_context():
        get_db().execute("UPDATE sessions SET last_seen = '2020-01-01T00:00:00+00:00' WHERE user_id = "
                         "(SELECT id FROM users WHERE username = 'beto')")
        get_db().commit()
    assert client.post("/admin/settings/sessions/close-idle", data={"_csrf": token, "hours": "5"}).status_code == 400
    client.post("/admin/settings/sessions/close-idle", data={"_csrf": token, "hours": "24"})
    assert {r["username"] for r in _sessions(app)} == {"root"}


def test_own_session_can_be_closed_from_the_list(app, admin):
    client, token = admin
    html = client.get("/admin/settings/sessions").get_data(as_text=True)
    assert "Cerrar (salir)" in html and "La tuya es la única sesión abierta." in html
    assert '<div class="muted small">root</div>' not in html  # el usuario no se repite si es el nombre visible
    client.post("/logout", data={"_csrf": token})
    assert _sessions(app) == [] and client.get("/f/home/").status_code == 302


from tests.helpers import PASSWORD, add_user, get_csrf, login
from storageweb.web.context import get_db


def test_requires_login(client):
    resp = client.get("/f/home/")
    assert resp.status_code == 302 and "/login" in resp.location


def test_login_page(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'name="username"' in html
    assert "Microsoft" not in html  # Entra desactivado


def test_post_without_csrf_rejected(app, client):
    add_user(app, "ana")
    resp = client.post("/login", data={"username": "ana", "password": PASSWORD})
    assert resp.status_code == 400


def test_wrong_password(app, client):
    add_user(app, "ana")
    resp = login(client, "ana", "incorrecta")
    assert resp.status_code == 200
    assert "incorrectos" in resp.get_data(as_text=True)


def test_unknown_user(client):
    resp = login(client, "nadie", "loquesea")
    assert "incorrectos" in resp.get_data(as_text=True)


def test_login_success_and_case_insensitive(app, client):
    add_user(app, "ana")
    resp = login(client, "ANA")
    assert resp.status_code == 302 and resp.location == "/"
    assert client.get("/f/home/").status_code == 200


def test_login_next_redirect_is_safe(app, client):
    add_user(app, "ana")
    assert login(client, "ana", next_url="/f/home/").location == "/f/home/"
    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    assert login(client, "ana", next_url="//evil.example").location == "/"


def test_disabled_user_cannot_login(app, client):
    uid = add_user(app, "ana")
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE users SET enabled = 0 WHERE id = ?", (uid,))
        conn.commit()
    assert "incorrectos" in login(client, "ana").get_data(as_text=True)


def test_disabling_user_kills_session(app, logged):
    client, _ = logged
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE users SET enabled = 0 WHERE username = 'ana'")
        conn.commit()
    assert client.get("/f/home/").status_code == 302


def test_local_login_can_be_disabled(make_app):
    app = make_app({"auth": {"local": {"enabled": False}, "entra": {
        "enabled": True, "tenant_id": "t", "client_id": "c", "client_secret": "s"}}})
    add_user(app, "ana")
    client = app.test_client()
    html = client.get("/login").get_data(as_text=True)
    assert 'name="username"' not in html
    assert client.post("/login", data={"username": "ana", "password": PASSWORD,
                                       "_csrf": get_csrf(client)}).status_code == 200
    assert client.get("/f/home/").status_code == 302


def test_entra_user_cannot_use_password_form(app, client):
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-1")
    assert "incorrectos" in login(client, "juan@contoso.com", "x").get_data(as_text=True)


def test_logout(logged):
    client, token = logged
    resp = client.post("/logout", data={"_csrf": token})
    assert resp.status_code == 302
    assert client.get("/f/home/").status_code == 302


def test_logout_requires_post(logged):
    client, _ = logged
    assert client.get("/logout").status_code == 405


def test_throttle_blocks_after_failures(make_app):
    app = make_app({"security": {"max_login_failures": 3}})
    add_user(app, "ana")
    client = app.test_client()
    for _ in range(3):
        login(client, "ana", "mal")
    resp = login(client, "ana")  # contraseña correcta, pero bloqueado
    assert "Demasiados" in resp.get_data(as_text=True)


def test_audit_records_login(app, client):
    add_user(app, "ana")
    login(client, "ana", "mal")
    login(client, "ana")
    with app.app_context():
        actions = [r["action"] for r in get_db().execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["login_failed", "login"]


def test_security_headers(client):
    resp = client.get("/login")
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_session_cookie_flags(make_app):
    app = make_app({"session": {"cookie_secure": True}})
    add_user(app, "ana")
    client = app.test_client()
    resp = login(client, "ana")
    cookie = resp.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie


def test_healthz_without_login(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok" and resp.get_json()["version"]

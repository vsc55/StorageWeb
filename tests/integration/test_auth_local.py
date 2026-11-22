
import io
import re

from storageweb import __version__
from tests.helpers import PASSWORD, add_user, get_csrf, last_audit, login
from storageweb.web.context import get_db


def test_requires_login(client):
    resp = client.get("/f/home/")
    assert resp.status_code == 302 and "/login" in resp.location


def test_login_page(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'name="username"' in html
    assert "Microsoft" not in html  # Entra desactivado
    # Solo cuenta local: el formulario a la vista, sin plegar, y la ilustración de serie en el lateral
    assert 'class="login-local"' not in html and "autofocus" in html
    assert "/static/img/login-classic.svg" in html and 'class="public-bar"' not in html
    assert '<use href="#i-logo">' in html and "/brand/favicon.svg?v=" in html   # logo y favicon de serie
    assert "StorageWeb " + __version__ not in html                             # la versión no se enseña sin sesión


def test_default_favicon_follows_the_main_color(make_app):
    app = make_app({"branding": {"primary_color": "#aa3300"}})
    resp = app.test_client().get("/brand/favicon.svg")
    assert resp.mimetype == "image/svg+xml" and 'fill="#aa3300"' in resp.get_data(as_text=True)


def test_with_sso_the_local_account_is_folded(make_app):
    app = make_app({"auth": {"entra": {"enabled": True, "tenant_id": "t", "client_id": "c", "client_secret": "s"}}})
    add_user(app, "ana")
    client = app.test_client()
    html = client.get("/login?manual=1").get_data(as_text=True)
    assert html.index("/auth/entra/login") < html.index('name="username"')   # Microsoft primero
    assert '<details class="login-local">' in html and "Usar una cuenta local" in html
    assert "autofocus" not in html                                            # el campo está plegado
    # Tras un intento fallido sale desplegado y con el usuario escrito
    html = login(client, "ana", "mal").get_data(as_text=True)
    assert '<details class="login-local" open>' in html and 'value="ana"' in html and "autofocus" in html


def test_custom_sign_in_image(app, admin):
    client, token = admin
    jpeg = b"\xff\xd8\xff" + b"\0" * 64
    resp = client.post("/admin/settings/branding/login-image",
                       data={"_csrf": token, "login_image": (io.BytesIO(jpeg), "foto.jpg")},
                       content_type="multipart/form-data")
    assert resp.status_code == 302
    html = app.test_client().get("/login").get_data(as_text=True)
    assert "/brand/login-image?v=" in html and "/static/img/login-classic.svg" not in html
    assert app.test_client().get("/brand/login-image").data == jpeg           # sin iniciar sesión
    with app.app_context():
        assert get_db().execute("SELECT 1 FROM audit_log WHERE action = 'branding_login_image_updated'").fetchone()
    client.post("/admin/settings/branding/login-image/delete", data={"_csrf": token})
    assert app.test_client().get("/brand/login-image").status_code == 404
    assert "/static/img/login-classic.svg" in app.test_client().get("/login").get_data(as_text=True)


def test_choose_sign_in_illustration(app, admin):
    client, token = admin
    page = client.get("/admin/settings/general").get_data(as_text=True)
    assert page.count('name="login_art"') == 6 and 'value="classic" checked' in page
    data = {"_csrf": token, "app_name": "StorageWeb", "default_locale": "es", "login_art": "waves"}
    assert client.post("/admin/settings/general", data=data).status_code == 302
    assert "/static/img/login-waves.svg" in app.test_client().get("/login").get_data(as_text=True)
    assert app.test_client().get("/static/img/login-waves.svg").status_code == 200
    html = client.post("/admin/settings/general", data={**data, "login_art": "../x"},
                       follow_redirects=True).get_data(as_text=True)
    assert "branding.login_art" in html                                       # valor no válido: no se guarda
    assert "/static/img/login-waves.svg" in app.test_client().get("/login").get_data(as_text=True)
    # Aleatoria: una de las cinco en cada carga
    assert client.post("/admin/settings/general", data={**data, "login_art": "random"}).status_code == 302
    seen = set()
    for _ in range(40):
        html = app.test_client().get("/login").get_data(as_text=True)
        seen.add(re.search(r"/static/img/login-(\w+)\.svg", html).group(1))
    assert len(seen) > 1 and seen <= {"classic", "sync", "waves", "mosaic", "layers"}


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
    # Con la contraseña buena se le dice por qué (es esa persona) y no cuenta como intento fallido
    resp = login(client, "ana")
    assert resp.status_code == 302
    assert "Tu cuenta está deshabilitada" in client.get(resp.location).get_data(as_text=True)
    assert last_audit(app, "login_failed")["detail"] == "account_disabled"
    # Con una contraseña mala, como siempre: no se revela nada
    page = login(client, "ana", password="otra-cosa").get_data(as_text=True)
    assert "incorrectos" in page and "desactivada" not in page


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
    assert resp.get_json() == {"status": "ok"}

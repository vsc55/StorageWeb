"""Verificación en dos pasos: que la contraseña deje de bastar, sin dejar fuera a nadie."""
import re

from storageweb.core import mfa
from storageweb.db.repositories import audit, users
from storageweb.settings import secretbox
from storageweb.web.context import get_db
from tests.helpers import PASSWORD, add_user, get_csrf, last_audit, login, settings_form, api_token, basic_auth
from tests.mfa_helpers import code, enrol, secrets_key, submit


def test_password_alone_is_not_a_session(app, client):
    add_user(app, "ana")
    secret, _codes = enrol(app, "ana")
    resp = login(client, "ana", next_url="/f/home/")
    assert resp.status_code == 302 and resp.location.endswith("/login/mfa")
    assert client.get("/f/home/").status_code == 302                   # sin sesión todavía
    page = client.get("/login/mfa").get_data(as_text=True)
    assert "Verificación en dos pasos" in page and 'autocomplete="one-time-code"' in page
    html = submit(client, "/login/mfa", "000000").get_data(as_text=True)
    assert "El código no es válido" in html and client.get("/f/home/").status_code == 302
    assert last_audit(app, "mfa_failed")["detail"] == "stage=verify error=bad_code"
    resp = submit(client, "/login/mfa", code(secret, 1))
    assert resp.status_code == 302 and resp.location.endswith("/f/home/")
    assert client.get("/f/home/").status_code == 200
    assert last_audit(app, "login")["detail"] == "local+totp"


def test_a_code_works_once_and_recovery_codes_too(app, client):
    add_user(app, "ana")
    secret, codes = enrol(app, "ana")
    login(client, "ana")
    once = code(secret, 1)          # el mismo código las dos veces (calcularlo otra vez podría caer en otro paso de 30 s)
    assert submit(client, "/login/mfa", once).status_code == 302
    client.post("/logout", data={"_csrf": get_csrf(client, "/profile")})
    login(client, "ana")
    assert "El código no es válido" in submit(client, "/login/mfa", once).get_data(as_text=True)
    # Un código de recuperación, en minúsculas y sin guion, vale una vez
    assert submit(client, "/login/mfa", codes[0].lower().replace("-", "")).status_code == 302
    assert last_audit(app, "login")["detail"] == "local+recovery" and last_audit(app, "mfa_recovery_used")
    client.post("/logout", data={"_csrf": get_csrf(client, "/profile")})
    login(client, "ana")
    assert "El código no es válido" in submit(client, "/login/mfa", codes[0]).get_data(as_text=True)
    with app.app_context():
        assert mfa.status(get_db(), users.get_by_username(get_db(), "ana"))["recovery_left"] == 9


def test_the_policy_makes_admins_set_it_up_at_sign_in(make_app):
    app = make_app({"security": {"mfa_required": "admins"}})
    add_user(app, "root", role="admin")
    add_user(app, "ana")
    client = app.test_client()
    assert login(client, "ana").location.endswith("/")                 # la política no le toca
    client = app.test_client()
    resp = login(client, "root", next_url="/admin/")
    assert resp.location.endswith("/login/mfa/enrol")                  # no se le deja fuera: lo configura aquí
    page = client.get("/login/mfa/enrol").get_data(as_text=True)
    assert "<svg" in page and "Configura la verificación en dos pasos" in page
    secret = re.search(r'value="([A-Z2-7 ]{20,})"', page).group(1)
    assert client.get("/admin/").status_code == 302
    resp = submit(client, "/login/mfa/enrol", code(secret))
    assert resp.location.endswith("/profile/mfa/codes")
    page = client.get("/profile/mfa/codes").get_data(as_text=True)
    assert len(re.findall(r"<code>[2-9A-Z]{5}-[2-9A-Z]{5}</code>", page)) == 10 and 'href="/admin/"' in page
    assert client.get("/profile/mfa/codes").status_code == 302          # una sola vez
    assert client.get("/admin/").status_code == 200
    assert last_audit(app, "mfa_enrolled")["detail"] == "forced"


def test_from_my_profile(app, logged):
    client, token = logged
    page = client.get("/profile/security").get_data(as_text=True)
    assert 'id="mfa"' in page and "Usar una aplicación de autenticación" in page
    assert client.post("/profile/mfa/begin", data={"_csrf": token}).location.endswith("/profile/mfa")
    page = client.get("/profile/mfa").get_data(as_text=True)
    secret = re.search(r'value="([A-Z2-7 ]{20,})"', page).group(1)
    assert client.get("/profile/mfa").get_data(as_text=True).count(secret) == 1   # recargar no cambia la semilla
    assert client.post("/profile/mfa/confirm", data={"_csrf": token, "code": "123"}).location.endswith("/profile/mfa")
    assert client.post("/profile/mfa/confirm", data={"_csrf": token, "code": code(secret)}).location.endswith(
        "/profile/mfa/codes")
    assert "Activada" in client.get("/profile/security").get_data(as_text=True)
    # Códigos nuevos y desactivar piden un código válido
    assert client.post("/profile/mfa/recovery", data={"_csrf": token, "code": "000000"}).location.endswith("#mfa")
    assert client.post("/profile/mfa/recovery", data={"_csrf": token, "code": code(secret, 1)}).location.endswith(
        "/profile/mfa/codes")
    fresh = re.findall(r"<code>([2-9A-Z]{5}-[2-9A-Z]{5})</code>", client.get("/profile/mfa/codes").get_data(as_text=True))
    assert len(fresh) == 10
    # Los pasos de la ventana ya están gastados (antirreplay): se desactiva con un código de recuperación nuevo
    client.post("/profile/mfa/disable", data={"_csrf": token, "code": fresh[0]})
    assert "Usar una aplicación de autenticación" in client.get("/profile/security").get_data(as_text=True)
    assert last_audit(app, "mfa_disabled")


def test_an_admin_removes_it_from_someone_else(app, admin):
    client, token = admin
    add_user(app, "ana")
    enrol(app, "ana")
    with app.app_context():
        ana = users.get_by_username(get_db(), "ana")
    page = client.get(f"/admin/users/{ana['uid']}").get_data(as_text=True)
    assert "Quitar la verificación en dos pasos" in page
    assert "Activada" in client.get("/admin/users").get_data(as_text=True)
    client.post(f"/admin/users/{ana['uid']}/mfa/reset", data={"_csrf": token})
    with app.app_context():
        assert not mfa.enrolled(get_db(), ana)
    assert last_audit(app, "mfa_reset_by_admin")["target"] == "ana"
    assert login(app.test_client(), "ana").location.endswith("/")     # vuelve a entrar solo con la contraseña


def test_the_network_drive_only_takes_tokens(make_app):
    app = make_app({"security": {"webdav_passwords": True}})
    add_user(app, "ana")
    client = app.test_client()

    def propfind(secret):
        return client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", secret)).status_code
    assert propfind(PASSWORD) == 207
    enrol(app, "ana")
    assert propfind(PASSWORD) == 401                                  # la contraseña sola ya no basta
    plain = api_token(app)
    with app.app_context():
        assert audit.recent(get_db(), 1)[0]["detail"] == "webdav:mfa_requires_token"
    assert propfind(plain) == 207


def test_wrong_codes_count_like_wrong_passwords(make_app):
    app = make_app({"security": {"max_login_failures": 3}})
    add_user(app, "ana")
    secret, _codes = enrol(app, "ana")
    client = app.test_client()
    login(client, "ana")
    for _ in range(2):
        submit(client, "/login/mfa", "000000")
    login(client, "ana")                                              # la contraseña correcta no reinicia la cuenta
    submit(client, "/login/mfa", "000000")
    assert "Demasiados intentos" in submit(client, "/login/mfa", code(secret, 1)).get_data(as_text=True)


def test_the_parked_sign_in_expires(app, client, monkeypatch):
    from storageweb.web.views import mfa as mfa_views
    add_user(app, "ana")
    secret, _codes = enrol(app, "ana")
    login(client, "ana")
    real = mfa_views.time.time
    monkeypatch.setattr(mfa_views.time, "time", lambda: real() + mfa_views.HOLD_SECONDS + 1)
    resp = client.get("/login/mfa")
    assert resp.status_code == 302 and "/login" in resp.location
    monkeypatch.undo()
    assert client.get("/login/mfa").status_code == 302                 # ya no hay nota


def test_policy_setting(app, admin):
    client, _token = admin
    data = settings_form(client, "auth")
    assert data["mfa_required"] == ["off"]
    data["mfa_required"] = ["all"]
    assert client.post("/admin/settings/auth", data=data).status_code == 302
    with app.app_context():
        from storageweb.web.context import settings
        assert settings()["security"]["mfa_required"] == "all"
    data["mfa_required"] = ["todos"]
    assert "security.mfa_required" in client.post("/admin/settings/auth", data=data).get_data(as_text=True)


def test_seeds_follow_a_new_secrets_key(app, client):
    add_user(app, "ana")
    secret, _codes = enrol(app, "ana")
    new = secretbox.parse_key(secretbox.generate_key())
    with app.app_context():
        assert secretbox.rekey(get_db(), secrets_key(app), new) >= 1
        app.extensions["storageweb.runtime"].secrets_key = new
    login(client, "ana")
    assert submit(client, "/login/mfa", code(secret, 1)).status_code == 302


def test_only_password_accounts(app):
    add_user(app, "ana")
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-1")
    with app.app_context():
        assert mfa.applies(users.get_by_username(get_db(), "ana"))
        assert not mfa.applies(users.get_by_username(get_db(), "juan@contoso.com"))   # usa el MFA de Microsoft

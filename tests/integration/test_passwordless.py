"""Entrar solo con una passkey (security.passkey_login): sin usuario ni contraseña, la passkey dice de quién es
(userHandle) y tiene que verificar a la persona (UV). Ceremonias enteras por HTTP con tests/webauthn_fabric.py."""
import pytest

from storageweb.core.mfa import webauthn as wa
from storageweb.db.repositories import users
from storageweb.web.context import get_db
from tests.helpers import add_user, get_csrf, login, get_user, last_audit
from tests.mfa_helpers import post_json, register
from tests.webauthn_fabric import ORIGIN, _assertion

ON = {"network": {"public_url": ORIGIN}, "security": {"passkey_login": True}}
UV = wa.FLAG_UP | wa.FLAG_UV


@pytest.fixture
def pl_app(make_app):
    return make_app(ON)


def _with_passkey(app, username="ana"):
    """Una cuenta con una passkey añadida en Mi perfil. Devuelve su clave privada."""
    add_user(app, username)
    client = app.test_client()
    login(client, username)
    token = get_csrf(client, "/profile/security")
    opts = post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token).get_json()
    assert opts["residentKey"] == "preferred"            # con esto encendido, guardada en el dispositivo
    priv, resp = register(client, token)
    assert resp.status_code == 200
    return priv


def _attempt(app, priv, *, flags=UV, handle=None, cred_id=b"cred-0001", count=2, next_url="/f/home/"):
    """Entrar sin contraseña como el navegador: opciones, aserción y envío. Devuelve ``(cliente, respuesta, cuerpo)``."""
    client = app.test_client()
    token = get_csrf(client, "/login")
    opts = post_json(client, f"/login/passkey/options?next={next_url}", {}, token)
    assert opts.status_code == 200, opts.get_json()
    o = opts.get_json()
    assert o["allow"] == [] and o["userVerification"] == "required"
    auth, cdj, sig = _assertion(priv, o["challenge"], flags=flags, count=count)
    if handle is None:
        handle = get_user(app)["uid"].encode()
    body = {"id": wa.b64u_encode(cred_id), "authenticator_data": wa.b64u_encode(auth),
            "client_data_json": wa.b64u_encode(cdj), "signature": wa.b64u_encode(sig),
            "user_handle": wa.b64u_encode(handle)}
    return client, post_json(client, "/login/passkey", body, token), body


def test_off_by_default(make_app):
    app = make_app({"network": {"public_url": ORIGIN}})
    add_user(app, "ana")
    page = app.test_client().get("/login").get_data(as_text=True)
    assert "/login/passkey/options" not in page and "passkeys.js" not in page
    client = app.test_client()
    token = get_csrf(client, "/login")
    assert post_json(client, "/login/passkey/options", {}, token).status_code == 400
    # Y las passkeys de Mi perfil no se piden guardadas en el dispositivo
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/profile/security")
    opts = post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token).get_json()
    assert opts["residentKey"] == "discouraged"


def test_sign_in_with_the_passkey_only(pl_app):
    priv = _with_passkey(pl_app)
    page = pl_app.test_client().get("/login").get_data(as_text=True)
    assert 'data-for="passwordless"' in page and "/static/js/passkeys.js" in page and "Entrar con una passkey" in page
    client, resp, _body = _attempt(pl_app, priv)
    assert resp.status_code == 200 and resp.get_json()["redirect"].endswith("/f/home/")
    assert client.get("/f/home/").status_code == 200                       # con sesión, sin código de nada
    assert last_audit(pl_app, "login")["detail"] == "local+passkey-only"
    assert get_user(pl_app)["last_login"]
    profile = client.get("/profile/security").get_data(as_text=True)
    assert "también puedes entrar sin tu contraseña" in profile


def test_the_person_must_be_verified_and_the_handle_must_match(pl_app):
    priv = _with_passkey(pl_app)
    add_user(pl_app, "luis")
    _c, resp, _b = _attempt(pl_app, priv, flags=wa.FLAG_UP)                # solo un toque, sin PIN ni huella
    assert resp.status_code == 400 and resp.get_json()["error"] == "La passkey no se ha aceptado."
    assert "user_verification_was_required" in last_audit(pl_app, "login_failed")["detail"]
    with pl_app.app_context():
        luis = users.get_by_username(get_db(), "luis")
    _c, resp, _b = _attempt(pl_app, priv, handle=luis["uid"].encode(), count=3)   # la passkey de ana «es» de luis
    assert resp.status_code == 400
    assert last_audit(pl_app, "login_failed")["detail"] == "passkey error=user_handle_does_not_match"
    _c, resp, _b = _attempt(pl_app, priv, handle=b"", count=4)             # sin userHandle (no residente)
    assert resp.status_code == 400
    _c, resp, _b = _attempt(pl_app, priv, cred_id=b"otra-cosa", count=5)   # una passkey que no es de nadie
    assert resp.status_code == 400
    assert last_audit(pl_app, "login_failed")["detail"] == "passkey error=unknown_credential"


def test_a_response_works_once(pl_app):
    priv = _with_passkey(pl_app)
    _client, resp, body = _attempt(pl_app, priv)
    assert resp.status_code == 200
    # Otra sesión, con su propio challenge, que manda la respuesta de antes: firmada sobre otro challenge
    other = pl_app.test_client()
    token = get_csrf(other, "/login")
    assert post_json(other, "/login/passkey/options", {}, token).status_code == 200
    again = post_json(other, "/login/passkey", body, token)
    assert again.status_code == 400 and again.get_json()["error"] == "La passkey no se ha aceptado."
    assert last_audit(pl_app, "login_failed")["detail"] == "passkey error=challenge_does_not_match"


def test_only_enabled_accounts_that_keep_their_password_here(pl_app):
    priv = _with_passkey(pl_app)
    with pl_app.app_context():
        users.update(get_db(), get_user(pl_app)["id"], enabled=0)
    client, resp, _b = _attempt(pl_app, priv)
    assert resp.status_code == 400 and "no puede entrar solo con una passkey" in resp.get_json()["error"]
    assert last_audit(pl_app, "login_failed")["detail"] == "passkey error=not_allowed"
    assert client.get("/f/home/").status_code == 302                       # sin sesión


def test_the_next_page_is_kept_and_checked(pl_app):
    priv = _with_passkey(pl_app)
    _c, resp, _b = _attempt(pl_app, priv, next_url="https://evil.example/")
    assert resp.get_json()["redirect"] == "/"


def test_failures_are_throttled(make_app):
    app = make_app({**ON, "security": {"passkey_login": True, "max_login_failures": 3}})
    priv = _with_passkey(app)
    # Passkeys que no son de nadie: cuentan por IP (no hay cuenta)
    for n in range(3):
        _c, resp, _b = _attempt(app, priv, cred_id=f"nadie-{n}".encode(), count=2 + n)
        assert resp.status_code == 400
    client = app.test_client()
    token = get_csrf(client, "/login")
    blocked = post_json(client, "/login/passkey/options", {}, token)
    assert blocked.status_code == 429

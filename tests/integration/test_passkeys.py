"""Passkeys como segundo paso: ceremonias enteras por HTTP (con las de tests/webauthn_fabric.py), su challenge de un
solo uso, la prueba antes de cambiar nada y que una cuenta con solo passkeys no se quede sin entrar."""
import re

import pytest

from storageweb.core import mfa
from storageweb.core.mfa import webauthn as wa
from storageweb.db.repositories import mfa as mfa_repo
from storageweb.db.repositories import users
from storageweb.web.context import get_db
from tests.helpers import add_user, get_csrf, login, settings_form
from tests.integration.test_mfa import code, enrol, last_audit, submit
from tests.webauthn_fabric import ORIGIN, _assertion, _registration

PUBLIC = {"network": {"public_url": ORIGIN}}


@pytest.fixture
def pk_app(make_app):
    return make_app(PUBLIC)


def post_json(client, url: str, body: dict, token: str):
    return client.post(url, json=body, headers={"X-CSRF-Token": token})


def register(client, token: str, *, name: str = "Portátil", cred_id: bytes = b"cred-0001",
             options="/profile/mfa/passkey/options", verify="/profile/mfa/passkey/register"):
    """Registra una passkey como el navegador. Devuelve ``(clave privada, respuesta)``."""
    opts = post_json(client, options, {"for": "register"}, token)
    assert opts.status_code == 200, opts.get_json()
    challenge = opts.get_json()["challenge"]
    priv, _key, att, cdj = _registration(challenge, cred_id=cred_id)
    resp = post_json(client, verify, {"attestation_object": wa.b64u_encode(att),
                                      "client_data_json": wa.b64u_encode(cdj), "name": name}, token)
    return priv, resp


def assertion_body(priv, challenge: str, *, cred_id: bytes = b"cred-0001", count: int = 2, origin: str = ORIGIN):
    auth, cdj, sig = _assertion(priv, challenge, count=count, origin=origin)
    return {"id": wa.b64u_encode(cred_id), "authenticator_data": wa.b64u_encode(auth),
            "client_data_json": wa.b64u_encode(cdj), "signature": wa.b64u_encode(sig)}


def sign_in(client, priv, *, count: int, cred_id: bytes = b"cred-0001", origin: str = ORIGIN):
    """Contraseña y passkey. Devuelve la respuesta de la passkey."""
    assert login(client, "ana", next_url="/f/home/").location.endswith("/login/mfa")
    token = get_csrf(client, "/login/mfa")
    opts = post_json(client, "/login/mfa/passkey/options", {}, token)
    assert opts.status_code == 200, opts.get_json()
    body = assertion_body(priv, opts.get_json()["challenge"], cred_id=cred_id, count=count, origin=origin)
    return post_json(client, "/login/mfa/passkey", body, token), body, token


def recovery_codes(client) -> list[str]:
    return re.findall(r"<code>([2-9A-Z]{5}-[2-9A-Z]{5})</code>", client.get("/profile/mfa/codes").get_data(as_text=True))


def logged_in(app, username: str = "ana"):
    add_user(app, username)
    client = app.test_client()
    assert login(client, username).status_code == 302
    return client, get_csrf(client, "/profile/security")


def ana(app):
    with app.app_context():
        return users.get_by_username(get_db(), "ana")


def test_add_from_my_profile_then_sign_in_with_it(pk_app):
    client, token = logged_in(pk_app)
    page = client.get("/profile/security").get_data(as_text=True)
    assert 'data-passkey="create"' in page and "/static/js/passkeys.js" in page
    opts = post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token).get_json()
    assert opts["rp"]["id"] == "panel.example.com" and opts["exclude"] == []
    assert wa.b64u_decode(opts["user"]["id"]).decode() == ana(pk_app)["uid"]     # el uid, no el nombre
    priv, resp = register(client, token)
    assert resp.get_json()["redirect"].endswith("/profile/mfa/codes")          # primer factor: códigos nuevos
    assert len(recovery_codes(client)) == 10
    assert last_audit(pk_app, "passkey_added")["target"] == "Portátil"
    assert last_audit(pk_app, "mfa_enrolled")["detail"] == "self passkey"
    with pk_app.app_context():
        state = mfa.status(get_db(), ana(pk_app))
    assert state["enrolled"] and not state["totp"] and [k["name"] for k in state["passkeys"]] == ["Portátil"]

    client = pk_app.test_client()
    resp, _body, _token = sign_in(client, priv, count=2)
    assert resp.get_json()["redirect"].endswith("/f/home/")
    assert client.get("/f/home/").status_code == 200
    assert last_audit(pk_app, "login")["detail"] == "local+passkey"


def test_the_login_page_offers_it_and_the_challenge_works_once(pk_app):
    client, token = logged_in(pk_app)
    priv, _resp = register(client, token)
    client = pk_app.test_client()
    login(client, "ana")
    page = client.get("/login/mfa").get_data(as_text=True)
    assert 'data-passkey="get"' in page and "XXXXX-XXXXX" in page              # sin app: código de recuperación
    resp, body, token = sign_in(client, priv, count=2)
    assert resp.status_code == 200
    # La misma respuesta otra vez: su challenge ya se gastó
    client2 = pk_app.test_client()
    login(client2, "ana")
    token2 = get_csrf(client2, "/login/mfa")
    post_json(client2, "/login/mfa/passkey/options", {}, token2)
    again = post_json(client2, "/login/mfa/passkey", body, token2)
    assert again.status_code == 400 and again.get_json()["error"] == "La passkey no se ha aceptado."
    assert last_audit(pk_app, "mfa_failed")["detail"] == "stage=passkey error=challenge_does_not_match"
    # Sin pedir challenge antes
    again = post_json(client2, "/login/mfa/passkey", body, token2)
    assert last_audit(pk_app, "mfa_failed")["detail"] == "stage=passkey error=no_challenge"


def test_wrong_origin_clone_and_another_account_are_refused(pk_app):
    client, token = logged_in(pk_app)
    priv, _resp = register(client, token)
    resp, *_ = sign_in(pk_app.test_client(), priv, count=2, origin="https://panel.example.com.evil.net")
    assert resp.status_code == 400
    assert last_audit(pk_app, "mfa_failed")["detail"] == "stage=passkey error=origin_does_not_match"
    assert sign_in(pk_app.test_client(), priv, count=5)[0].status_code == 200
    resp, *_ = sign_in(pk_app.test_client(), priv, count=5)                     # el contador no avanza: clonada
    assert last_audit(pk_app, "mfa_failed")["detail"] == "stage=passkey error=the_signature_counter_went_backwards"
    # La credencial de ana no vale para otra cuenta
    add_user(pk_app, "luis")
    other = pk_app.test_client()
    login(other, "luis")
    t = get_csrf(other, "/profile/security")
    register(other, t, cred_id=b"cred-luis")
    other = pk_app.test_client()
    login(other, "luis")
    t = get_csrf(other, "/login/mfa")
    opts = post_json(other, "/login/mfa/passkey/options", {}, t).get_json()
    assert opts["allow"] == [wa.b64u_encode(b"cred-luis")]
    resp = post_json(other, "/login/mfa/passkey", assertion_body(priv, opts["challenge"], count=9), t)
    assert resp.status_code == 400 and last_audit(pk_app, "mfa_failed")["detail"].endswith("unknown_credential")


def test_adding_or_removing_needs_proof(pk_app):
    client, token = logged_in(pk_app)
    priv, _resp = register(client, token)
    client = pk_app.test_client()
    resp, _body, _t = sign_in(client, priv, count=2)
    token = get_csrf(client, "/profile/security")
    page = client.get("/profile/security").get_data(as_text=True)
    assert "Confirma que eres tú" in page and "/profile/mfa/passkey/1/remove" not in page
    # Una segunda passkey con la sesión sola: no
    assert post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token).status_code == 403
    assert client.post("/profile/mfa/passkey/1/remove", data={"_csrf": token}).location.endswith("#mfa")
    with pk_app.app_context():
        assert mfa_repo.passkey_count(get_db(), ana(pk_app)["id"]) == 1
    # Demostrarlo con la passkey abre unos minutos para cambiar cosas
    opts = post_json(client, "/profile/mfa/passkey/options", {"for": "prove"}, token).get_json()
    proved = post_json(client, "/profile/mfa/passkey/prove", assertion_body(priv, opts["challenge"], count=3), token)
    assert proved.get_json()["redirect"].endswith("#mfa")
    assert "/profile/mfa/passkey/1/remove" in client.get("/profile/security").get_data(as_text=True)
    _priv2, resp = register(client, token, name="Llave USB", cred_id=b"cred-0002")
    assert resp.get_json()["redirect"].endswith("#mfa")                         # ya tenía códigos: no se cambian
    client.post("/profile/mfa/passkey/1/rename", data={"_csrf": token, "name": "  Portátil   del trabajo "})
    assert last_audit(pk_app, "passkey_renamed")["target"] == "Portátil del trabajo"
    with pk_app.app_context():
        names = [k["name"] for k in mfa.status(get_db(), ana(pk_app))["passkeys"]]
        left = mfa.status(get_db(), ana(pk_app))["recovery_left"]
    assert names == ["Portátil del trabajo", "Llave USB"] and left == 10
    # Quitar las dos: con la última se va la verificación entera (y los códigos)
    client.post("/profile/mfa/passkey/1/remove", data={"_csrf": token})
    client.post("/profile/mfa/passkey/2/remove", data={"_csrf": token})
    assert last_audit(pk_app, "passkey_removed")["target"] == "Llave USB"
    with pk_app.app_context():
        state = mfa.status(get_db(), ana(pk_app))
        assert not state["enrolled"] and mfa_repo.recovery_unused(get_db(), ana(pk_app)["id"]) == []
    assert login(pk_app.test_client(), "ana").location.endswith("/")


def test_recovery_codes_work_for_an_account_with_only_passkeys(pk_app):
    client, token = logged_in(pk_app)
    register(client, token)
    codes = recovery_codes(client)
    client = pk_app.test_client()
    login(client, "ana")
    assert submit(client, "/login/mfa", "000000").status_code == 200
    resp = submit(client, "/login/mfa", codes[0])
    assert resp.status_code == 302 and last_audit(pk_app, "login")["detail"] == "local+recovery"


def test_app_and_passkeys_together(pk_app):
    add_user(pk_app, "ana")
    secret, codes = enrol(pk_app, "ana")
    client = pk_app.test_client()
    login(client, "ana")
    assert submit(client, "/login/mfa", code(secret, 1)).status_code == 302
    token = get_csrf(client, "/profile/security")
    # Con la app activa, añadir una passkey pide confirmar antes; un código vale
    assert post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token).status_code == 403
    assert client.post("/profile/mfa/prove", data={"_csrf": token, "code": codes[0]}).location.endswith("#mfa")
    priv, resp = register(client, token)
    assert resp.get_json()["redirect"].endswith("#mfa")
    # Quitar solo la app: las passkeys y los códigos siguen
    client.post("/profile/mfa/totp/remove", data={"_csrf": token})
    assert last_audit(pk_app, "mfa_disabled")["detail"] == "self app"
    with pk_app.app_context():
        state = mfa.status(get_db(), ana(pk_app))
    assert state["enrolled"] and not state["totp"] and state["recovery_left"] == 9
    # Volver a poner la app (con la prueba aún vigente) no cambia los códigos
    assert client.post("/profile/mfa/begin", data={"_csrf": token}).location.endswith("/profile/mfa")
    with pk_app.app_context():
        setup = mfa.pending_setup(get_db(), pk_app.extensions["storageweb.runtime"].secrets_key, ana(pk_app), "x")
    resp = client.post("/profile/mfa/confirm", data={"_csrf": token, "code": code(setup["secret"])})
    assert resp.location.endswith("#mfa")
    # Cancelar un alta a medias de la app no toca las passkeys
    client.post("/profile/mfa/totp/remove", data={"_csrf": token})
    client.post("/profile/mfa/begin", data={"_csrf": token})
    client.post("/profile/mfa/cancel", data={"_csrf": token})
    with pk_app.app_context():
        state = mfa.status(get_db(), ana(pk_app))
    assert len(state["passkeys"]) == 1 and not state["pending"] and state["recovery_left"] == 9
    # Desactivar lo quita todo
    client.post("/profile/mfa/disable", data={"_csrf": token})
    with pk_app.app_context():
        assert not mfa.enrolled(get_db(), ana(pk_app))
    assert login(pk_app.test_client(), "ana").location.endswith("/")


def test_forced_enrolment_with_a_passkey(make_app):
    app = make_app({**PUBLIC, "security": {"mfa_required": "all"}})
    add_user(app, "ana")
    client = app.test_client()
    assert login(client, "ana", next_url="/f/home/").location.endswith("/login/mfa/enrol")
    page = client.get("/login/mfa/enrol").get_data(as_text=True)
    assert 'data-passkey="create"' in page and "<svg" in page                 # las dos formas
    token = get_csrf(client, "/login/mfa/enrol")
    _priv, resp = register(client, token, options="/login/mfa/enrol/passkey/options",
                           verify="/login/mfa/enrol/passkey")
    assert resp.get_json()["redirect"].endswith("/profile/mfa/codes")
    assert 'href="/f/home/"' in client.get("/profile/mfa/codes").get_data(as_text=True)
    assert client.get("/f/home/").status_code == 200
    assert last_audit(app, "mfa_enrolled")["detail"] == "forced passkey"
    assert last_audit(app, "login")["detail"] == "local+passkey"
    with app.app_context():
        state = mfa.status(get_db(), ana(app))
    assert not state["pending"] and len(state["passkeys"]) == 1               # el alta de la app a medias, fuera


def test_not_offered_without_a_usable_public_address(make_app):
    for n, public in enumerate(("", "http://files.example.com", "https://10.0.0.5")):
        app = make_app({"network": {"public_url": public}})
        client, token = logged_in(app, f"u{n}")
        assert 'data-passkey="create"' not in client.get("/profile/security").get_data(as_text=True)
        resp = post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token)
        assert resp.status_code == 400
    app = make_app({"network": {"public_url": ORIGIN}, "security": {"passkeys": False}})
    client, token = logged_in(app, "u9")
    assert post_json(client, "/profile/mfa/passkey/options", {"for": "register"}, token).status_code == 400


def test_the_setting(make_app):
    app = make_app(PUBLIC)
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    data = settings_form(client, "auth")
    assert data["passkeys"] == ["on"]
    assert "panel.example.com" in client.get("/admin/settings/auth").get_data(as_text=True)
    del data["passkeys"]
    assert client.post("/admin/settings/auth", data=data).status_code == 302
    with app.app_context():
        from storageweb.web.context import settings
        assert settings()["security"]["passkeys"] is False


def test_status_for_the_admin_and_the_cli(pk_app, capsys):
    client, token = logged_in(pk_app)
    register(client, token)
    add_user(pk_app, "root", role="admin")
    admin = pk_app.test_client()
    login(admin, "root")
    page = admin.get(f"/admin/users/{ana(pk_app)['uid']}").get_data(as_text=True)
    assert "1 passkey" in page and "Quitar la verificación en dos pasos" in page
    from storageweb.cli.security import cmd_mfa_status
    with pk_app.app_context():
        from storageweb.web.context import settings
        cmd_mfa_status(settings(), get_db(), None)
    assert "activada: 1 passkey" in capsys.readouterr().out

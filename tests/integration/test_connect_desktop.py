"""Entrar desde VS Code con la cuenta de Windows (/connect/desktop): la extensión canjea un token de Microsoft para la
API de StorageWeb por un token de API, con las mismas reglas que el inicio de sesión de Entra ID."""
from __future__ import annotations

import pytest

from storageweb.db.repositories import api_tokens, users
from storageweb.web.context import get_db
from tests.entra_keys import OTHER_KEY, fake_microsoft, token
from tests.helpers import add_user, basic_auth, last_audit, update_settings
from tests.sso_helpers import CLIENT_ID, TENANT

URL = "/connect/desktop"


@pytest.fixture
def app(entra_app, monkeypatch):
    fake_microsoft(monkeypatch)
    return entra_app(desktop_sign_in=True)


def _redeem(http, tok, **extra):
    return http.post(URL, json={"method": "entra", "client": "vscode", "access_token": tok, "device": "PC-JUAN",
                                **extra})


def test_what_the_extension_has_to_ask(app, entra_app):
    found = app.test_client().get(URL).get_json()["methods"]
    assert found == [{"key": "entra", "label": "Entra ID", "provider": "microsoft", "tenant": TENANT,
                      "scopes": [f"api://{CLIENT_ID}/access_as_user"]}]
    off = entra_app()                                                   # sin activar: no se ofrece
    assert off.test_client().get(URL).get_json()["methods"] == []
    assert _redeem(off.test_client(), token()).status_code == 404


def test_a_windows_account_gets_a_token(app):
    resp = _redeem(app.test_client(), token())
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"
    data = resp.get_json()
    assert data["username"] == "juan@contoso.com" and data["name"] == "Visual Studio Code (PC-JUAN)"
    assert data["token"].startswith("sw_") and data["days"] == 90
    with app.app_context():
        user = users.get_by_username(get_db(), "juan@contoso.com")
        assert user["source"] == "entra" and user["external_id"] == "oid-juan"     # alta automática, como al entrar
        assert [t["name"] for t in api_tokens.list_for_user(get_db(), user["id"])] == ["Visual Studio Code (PC-JUAN)"]
    # El token vale para la unidad de red
    dav = app.test_client().open("/dav/", method="PROPFIND", headers={**basic_auth("juan@contoso.com", data["token"]),
                                                                       "Depth": "1"})
    assert dav.status_code == 207
    assert last_audit(app, "app_authorized")["detail"] == "entra:desktop"
    assert last_audit(app, "api_token_created")["detail"] == "connect-desktop"


def test_a_bad_microsoft_token_is_refused_and_counted(app, monkeypatch):
    from storageweb.core import ipban
    offenses = []
    monkeypatch.setattr(ipban, "offense", lambda conn, cfg, ip, kind: offenses.append(kind))
    for bad in (token(key=OTHER_KEY), token(scp="User.Read"), "no-es-un-token"):
        resp = _redeem(app.test_client(), bad)
        assert resp.status_code == 401 and resp.get_json()["error"] == "invalid_token"
    assert offenses == ["bad_token"] * 3
    assert last_audit(app, "login_failed")["detail"] == "entra:desktop:invalid_token"
    # Un token auténtico pero caducado, de otra organización o pedido por otra aplicación no es un ataque: no cuenta
    # (la IP de una oficina entera)
    other = "99999999-2222-3333-4444-555555555555"
    for genuine in (token(exp=1), token(tid=other, iss=f"https://login.microsoftonline.com/{other}/v2.0"),
                    token(azp="otra-app")):
        assert _redeem(app.test_client(), genuine).status_code == 401
    assert offenses == ["bad_token"] * 3
    # Falsificado y de otra organización: la firma se mira antes, cuenta
    assert _redeem(app.test_client(), token(tid=other, key=OTHER_KEY)).status_code == 401
    assert offenses == ["bad_token"] * 4


def test_microsoft_unreachable(app, monkeypatch):
    from storageweb.providers.entra import access_token, register
    monkeypatch.setattr(access_token, "_request", lambda *a, **kw: (_ for _ in ()).throw(register.RegisterError("x")))
    access_token.clear_cache()
    for _n in range(3):
        resp = _redeem(app.test_client(), token())
        assert resp.status_code == 503 and resp.get_json()["error"] == "unavailable"
    with app.app_context():                     # sin llenar la auditoría: cualquiera, sin autenticar, podría
        rows = get_db().execute("SELECT COUNT(*) FROM audit_log WHERE action = 'login_failed'").fetchone()[0]
    assert rows == 0


def test_not_offered_for_personal_accounts(entra_app, monkeypatch):
    fake_microsoft(monkeypatch)
    app = entra_app(desktop_sign_in=True, tenant_id="consumers")
    assert app.test_client().get(URL).get_json()["methods"] == []
    assert _redeem(app.test_client(), token()).status_code == 404


def test_a_client_that_is_not_text(app):
    for client in ([], {"a": 1}, 7, None):
        resp = _redeem(app.test_client(), token(), client=client)
        assert resp.status_code == 400 and resp.get_json()["error"] == "unknown_client"


def test_an_account_the_directory_disabled_is_not_enabled_again(app):
    """El token de Microsoft vale ~1 h: puede ser de antes de que el directorio desactivara la cuenta (la web sí la
    reactiva, su id_token es siempre nuevo)."""
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-juan")
    with app.app_context():
        uid = users.get_by_username(get_db(), "juan@contoso.com")["id"]
        users.update(get_db(), uid, enabled=0, disabled_reason=users.DIRECTORY)
    resp = _redeem(app.test_client(), token())
    assert resp.status_code == 403 and resp.get_json()["error"] == "denied"
    with app.app_context():
        assert not users.get_by_id(get_db(), uid)["enabled"]


def test_the_email_is_kept_when_the_token_has_none(app):
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-juan")
    with app.app_context():
        uid = users.get_by_username(get_db(), "juan@contoso.com")["id"]
        users.update(get_db(), uid, email="juan.perez@correo.contoso.com")
    assert _redeem(app.test_client(), token()).status_code == 200
    with app.app_context():
        assert users.get_by_id(get_db(), uid)["email"] == "juan.perez@correo.contoso.com"


def test_a_body_that_is_not_an_object(app):
    for body in ([1, 2], "texto", 7, None):
        resp = app.test_client().post(URL, json=body)
        assert resp.status_code == 404 and resp.get_json()["error"] == "not_enabled"


def test_without_the_user_name_claim_it_is_refused_not_renamed(entra_app, monkeypatch):
    """El token de acceso no trae «upn» (el id_token sí, como claim opcional): sin él no se entra con otro nombre
    (el email), que renombraría la cuenta y su carpeta."""
    fake_microsoft(monkeypatch)
    app = entra_app(desktop_sign_in=True, username_claim="upn")
    add_user(app, "juan.upn@contoso.com", password=None, source="entra", external_id="oid-juan")
    resp = _redeem(app.test_client(), token(email="juan@contoso.com"))
    assert resp.status_code == 403 and "upn" in resp.get_json()["message"]
    with app.app_context():
        assert users.get_by_username(get_db(), "juan.upn@contoso.com") is not None      # sin renombrar
    assert _redeem(app.test_client(), token(upn="Juan.UPN@contoso.com")).get_json()["username"] == "juan.upn@contoso.com"


def test_the_allowed_groups_apply(entra_app, monkeypatch):
    fake_microsoft(monkeypatch)
    strict = entra_app(desktop_sign_in=True, allowed_groups=["g-permitido"])
    resp = _redeem(strict.test_client(), token(groups=["g-otro"]))
    assert resp.status_code == 403 and resp.get_json()["error"] == "denied"
    assert "no tiene permiso" in resp.get_json()["message"]
    assert _redeem(strict.test_client(), token(groups=["g-permitido"])).status_code == 200


def test_a_disabled_account_cannot(app):
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-juan")
    with app.app_context():
        users.update(get_db(), users.get_by_username(get_db(), "juan@contoso.com")["id"], enabled=0)
    resp = _redeem(app.test_client(), token())
    assert resp.status_code == 403 and "deshabilitada" in resp.get_json()["message"]


def test_tokens_disabled_and_unknown_client(app):
    assert _redeem(app.test_client(), token(), client="otra-app").get_json()["error"] == "unknown_client"
    update_settings(app, security={"api_tokens": False})
    resp = _redeem(app.test_client(), token())
    assert resp.status_code == 403 and resp.get_json()["error"] == "tokens_disabled"


def test_no_csrf_and_no_session_needed(app):
    """La extensión no tiene cookies: el canje no pide token CSRF (el secreto es el token de Microsoft, firmado)."""
    client = app.test_client()
    assert _redeem(client, token()).status_code == 200

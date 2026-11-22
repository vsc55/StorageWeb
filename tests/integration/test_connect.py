"""Conectar una aplicación iniciando sesión en el navegador (/connect): OAuth con PKCE (core/connect.py)."""
from __future__ import annotations

import re
import secrets
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest

from storageweb.core import connect
from storageweb.db.repositories import api_tokens, audit, users
from storageweb.web.context import get_db

from tests.helpers import add_user, csrf_from, login, signed_in, basic_auth

REDIRECT = "vscode://storageweb.storageweb-sync/auth"


@pytest.fixture(autouse=True)
def _clear():
    connect.clear()
    yield
    connect.clear()


def _pkce():
    verifier = secrets.token_urlsafe(48)
    return verifier, connect.challenge_of(verifier)


def _start(client, challenge, state="estado-de-prueba-123", redirect=REDIRECT, device="PORTATIL-01"):
    return client.get("/connect/vscode", query_string={"redirect_uri": redirect, "challenge": challenge,
                                                        "state": state, "device": device})


def _allow(client, challenge, state="estado-de-prueba-123", action="allow", **extra):
    page = _start(client, challenge, state)
    assert page.status_code == 200
    form = {"_csrf": csrf_from(page.get_data(as_text=True)), "redirect_uri": REDIRECT, "state": state,
            "challenge": challenge, "device": "PORTATIL-01", "action": action, "scope": "write", "days": "365", **extra}
    resp = client.post("/connect/vscode", data=form)
    assert resp.status_code == 200
    target = unescape(re.search(r'id="connect-return" href="([^"]+)"', resp.get_data(as_text=True)).group(1))
    assert target.startswith(REDIRECT + "?")
    return parse_qs(urlsplit(target).query)


def test_full_flow_gives_a_working_token(app, logged):
    client, _csrf = logged
    verifier, challenge = _pkce()
    page = _start(client, challenge).get_data(as_text=True)
    assert "Visual Studio Code" in page and "PORTATIL-01" in page and "ana" in page
    back = _allow(client, challenge)
    assert back["state"] == ["estado-de-prueba-123"]
    code = back["code"][0]

    # Otro cliente (la extensión, sin cookies) canjea el código con el verifier
    app_client = app.test_client()
    resp = app_client.post("/connect/token", json={"code": code, "verifier": verifier})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.headers["Cache-Control"] == "no-store"
    data = resp.get_json()
    assert data["username"] == "ana"
    assert data["name"] == "Visual Studio Code (PORTATIL-01)"
    assert app_client.open("/dav/home/", method="PROPFIND", headers={**basic_auth("ana", data["token"]), "Depth": "1"}).status_code == 207

    # Un solo uso
    assert app_client.post("/connect/token", json={"code": code, "verifier": verifier}).status_code == 400
    with app.app_context():
        user = users.get_by_username(get_db(), "ana")
        names = [t["name"] for t in api_tokens.list_for_user(get_db(), user["id"])]
        actions = [(r["action"], r["detail"]) for r in audit.recent(get_db(), limit=20)]
    assert names == ["Visual Studio Code (PORTATIL-01)"]
    assert ("app_authorized", "PORTATIL-01") in actions
    assert ("api_token_created", "connect") in actions


def test_code_without_the_right_verifier_is_useless(app, logged):
    client, _csrf = logged
    verifier, challenge = _pkce()
    code = _allow(client, challenge)["code"][0]
    other = app.test_client()
    assert other.post("/connect/token", json={"code": code, "verifier": secrets.token_urlsafe(48)}).status_code == 400
    # El intento fallido gasta el código: ni con el verifier bueno
    assert other.post("/connect/token", json={"code": code, "verifier": verifier}).status_code == 400
    assert other.post("/connect/token", json={"code": "inventado", "verifier": verifier}).status_code == 400
    with app.app_context():
        assert api_tokens.list_for_user(get_db(), users.get_by_username(get_db(), "ana")["id"]) == []


def test_denied_returns_an_error_and_no_code(logged):
    client, _csrf = logged
    _verifier, challenge = _pkce()
    back = _allow(client, challenge, action="deny")
    assert back["error"] == ["access_denied"] and "code" not in back


@pytest.mark.parametrize("redirect", [
    "https://evil.example.com/auth", "vscode://otra.extension/auth", "vscode://storageweb.storageweb-sync/auth/../x",
    "vscode://storageweb.storageweb-sync/auth?x=1", "javascript:alert(1)", ""])
def test_only_the_extension_return_address_is_allowed(logged, redirect):
    client, _csrf = logged
    _verifier, challenge = _pkce()
    resp = _start(client, challenge, redirect=redirect)
    assert resp.status_code == 400
    assert "connect-return" not in resp.get_data(as_text=True)  # nada a lo que volver


def test_bad_requests_and_login_required(app, client, logged):
    _verifier, challenge = _pkce()
    fresh = app.test_client()
    resp = _start(fresh, challenge)
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]  # primero, iniciar sesión
    logged_client, _csrf = logged
    assert _start(logged_client, "corto").status_code == 400
    assert _start(logged_client, challenge, state="x").status_code == 400
    assert logged_client.get("/connect/otra-app", query_string={"redirect_uri": REDIRECT, "challenge": challenge,
                                                                 "state": "estado-de-prueba-123"}).status_code == 400
    # El POST de la página necesita el CSRF de la sesión (el canje, no)
    resp = logged_client.post("/connect/vscode", data={"redirect_uri": REDIRECT, "challenge": challenge,
                                                       "state": "estado-de-prueba-123", "action": "allow"})
    assert resp.status_code == 400


def test_login_then_back_to_the_authorization_page(app, client):
    add_user(app, "ana")
    _verifier, challenge = _pkce()
    first = _start(client, challenge)
    next_url = parse_qs(urlsplit(first.headers["Location"]).query)["next"][0]
    assert next_url.startswith("/connect/vscode?")
    resp = login(client, "ana", next_url=next_url)
    assert resp.headers["Location"].endswith(next_url) or next_url in resp.headers["Location"]


def test_disabled_when_api_tokens_are_off(make_app):
    app = make_app({"security": {"api_tokens": False}})
    client, _ = signed_in(app, "ana", csrf_url=None)
    _verifier, challenge = _pkce()
    assert _start(client, challenge).status_code == 403
    assert app.test_client().post("/connect/token", json={"code": "x", "verifier": "y" * 43}).status_code == 403


def test_device_name_is_cleaned():
    assert connect.clean_device("  PC <script>  de\nAna  ") == "PC script de Ana"
    assert len(connect.clean_device("x" * 200)) == 40
    assert connect.clean_device(None) == ""

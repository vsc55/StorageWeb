import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from src import db
from src.db import users
from src.providers import SSOError, msal_provider, oauth2

from .conftest import add_user, get_csrf

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT_ID = "cid-123"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"


def b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def make_jwt(claims: dict) -> str:
    return f"{b64({'alg': 'RS256', 'typ': 'JWT'})}.{b64(claims)}.firma"


def base_claims(expected_nonce: str, **extra) -> dict:
    now = int(time.time())
    claims = {"aud": CLIENT_ID, "iss": ISSUER, "tid": TENANT, "iat": now, "nbf": now,
              "exp": now + 3600, "nonce": expected_nonce, "oid": "oid-juan",
              "preferred_username": "Juan@Contoso.com", "name": "Juan Pérez"}
    claims.update(extra)
    return claims


def entra_cfg(**extra) -> dict:
    cfg = {"enabled": True, "provider": "oauth2", "tenant_id": TENANT, "client_id": CLIENT_ID,
           "client_secret": "secreto", "redirect_uri": "https://files.ejemplo.com/auth/entra/callback"}
    cfg.update(extra)
    return cfg


@pytest.fixture
def token_endpoint(monkeypatch):
    """Sustituye la llamada HTTP al endpoint de token. Configura .response o .claims."""
    class Endpoint:
        calls: list = []
        response = None
        claims_extra: dict = {}

        def __call__(self, url, data, timeout):
            self.calls.append({"url": url, "data": data, "timeout": timeout})
            if self.response is not None:
                return self.response
            return {"id_token": make_jwt(base_claims(self.nonce, **self.claims_extra)),
                    "access_token": "at", "token_type": "Bearer"}

    ep = Endpoint()
    ep.calls = []
    monkeypatch.setattr(oauth2, "_http_post", ep)
    return ep


@pytest.fixture
def entra_app(make_app):
    def _make(**entra):
        return make_app({"auth": {"entra": entra_cfg(**entra)}})
    return _make


def start_login(client, token_endpoint, next_url=""):
    resp = client.get(f"/auth/entra/login?next={next_url}")
    assert resp.status_code == 302
    url = urlparse(resp.location)
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    token_endpoint.nonce = q["nonce"]
    return url, q


def finish_login(client, state, **params):
    query = "&".join(f"{k}={v}" for k, v in {"code": "codigo", "state": state, **params}.items())
    return client.get(f"/auth/entra/callback?{query}")


# --------------------------------------------------------------------------- flujo completo


def test_login_button_visible(entra_app):
    html = entra_app().test_client().get("/login").get_data(as_text=True)
    assert "Iniciar sesión con Microsoft" in html


def test_authorize_request(entra_app, token_endpoint):
    client = entra_app().test_client()
    url, q = start_login(client, token_endpoint)
    assert url.netloc == "login.microsoftonline.com"
    assert url.path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
    assert q["redirect_uri"] == "https://files.ejemplo.com/auth/entra/callback"
    assert q["code_challenge_method"] == "S256"
    assert set(q["scope"].split()) >= {"openid", "profile", "email", "User.Read"}
    assert q["state"] and q["nonce"] and q["state"] != q["nonce"]


def test_full_login_provisions_user(entra_app, token_endpoint, tmp_path):
    app = entra_app()
    client = app.test_client()
    _, q = start_login(client, token_endpoint, next_url="/f/home/")
    resp = finish_login(client, q["state"])
    assert resp.status_code == 302 and resp.location == "/f/home/"

    call = token_endpoint.calls[0]
    assert call["url"] == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    assert call["data"]["code"] == "codigo"
    assert call["data"]["client_secret"] == "secreto"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(call["data"]["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"]

    html = client.get("/f/home/").get_data(as_text=True)
    assert "Juan Pérez" in html
    assert (tmp_path / "data" / "homes" / "juan@contoso.com").is_dir()
    with app.app_context():
        user = users.get_by_username("juan@contoso.com")
        assert user["source"] == "entra" and user["external_id"] == "oid-juan"


def test_second_login_reuses_user_by_oid(entra_app, token_endpoint):
    app = entra_app()
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    token_endpoint.claims_extra = {"preferred_username": "juan.nuevo@contoso.com"}
    _, q = start_login(client, token_endpoint)
    assert finish_login(client, q["state"]).status_code == 302
    with app.app_context():
        assert db.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_strip_domain(entra_app, token_endpoint):
    app = entra_app(strip_domain=True)
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    with app.app_context():
        assert users.get_by_username("juan") is not None


@pytest.mark.parametrize("bad_claims", [
    {"aud": "otra-app"},
    {"iss": "https://login.microsoftonline.com/otro-tenant/v2.0"},
    {"tid": "otro-tenant"},
    {"exp": int(time.time()) - 3600},
    {"nbf": int(time.time()) + 3600},
    {"nonce": "nonce-falso"},
    {"oid": None, "sub": None},
    {"preferred_username": None, "email": None},
])
def test_invalid_tokens_rejected(entra_app, token_endpoint, bad_claims):
    client = entra_app().test_client()
    token_endpoint.claims_extra = bad_claims
    _, q = start_login(client, token_endpoint)
    resp = finish_login(client, q["state"])
    assert resp.status_code == 302 and "/login" in resp.location
    assert client.get("/f/home/").status_code == 302


def test_state_mismatch(entra_app, token_endpoint):
    client = entra_app().test_client()
    start_login(client, token_endpoint)
    resp = finish_login(client, "otro-state")
    assert "/login" in resp.location
    assert token_endpoint.calls == []  # no se llega a canjear el código


def test_callback_without_flow(entra_app, token_endpoint):
    client = entra_app().test_client()
    resp = finish_login(client, "x")
    assert "/login" in resp.location


def test_provider_error_param(entra_app, token_endpoint):
    client = entra_app().test_client()
    _, q = start_login(client, token_endpoint)
    resp = client.get(f"/auth/entra/callback?state={q['state']}&error=access_denied")
    assert "/login" in resp.location
    assert token_endpoint.calls == []


def test_token_endpoint_error(entra_app, token_endpoint):
    client = entra_app().test_client()
    token_endpoint.response = {"error": "invalid_grant", "error_description": "AADSTS..."}
    _, q = start_login(client, token_endpoint)
    assert "/login" in finish_login(client, q["state"]).location


def test_network_error(entra_app, monkeypatch):
    client = entra_app(token_url="http://127.0.0.1:9/token", timeout_seconds=1).test_client()
    resp = client.get("/auth/entra/login")
    state = parse_qs(urlparse(resp.location).query)["state"][0]
    resp = finish_login(client, state)
    assert "/login" in resp.location


def test_expired_flow(entra_app, token_endpoint, monkeypatch):
    client = entra_app().test_client()
    _, q = start_login(client, token_endpoint)
    real = time.time
    monkeypatch.setattr(oauth2.time, "time", lambda: real() + oauth2.FLOW_MAX_AGE + 5)
    assert "/login" in finish_login(client, q["state"]).location
    assert token_endpoint.calls == []


def test_allowed_groups_and_roles(entra_app, token_endpoint):
    app = entra_app(allowed_groups=["GRP-FIN", "StorageWeb.User"])
    client = app.test_client()

    token_endpoint.claims_extra = {"groups": ["otro"]}
    _, q = start_login(client, token_endpoint)
    assert "/login" in finish_login(client, q["state"]).location

    token_endpoint.claims_extra = {"groups": ["grp-fin"]}
    _, q = start_login(client, token_endpoint)
    assert finish_login(client, q["state"]).location == "/"
    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})

    token_endpoint.claims_extra = {"roles": ["StorageWeb.User"]}
    _, q = start_login(client, token_endpoint)
    assert finish_login(client, q["state"]).location == "/"


def test_group_based_share(make_app, token_endpoint, tmp_path):
    (tmp_path / "fin").mkdir()
    app = make_app({"auth": {"entra": entra_cfg()}, "storage": {"shares": [
        {"name": "finanzas", "path": str(tmp_path / "fin"), "users": [], "groups": ["grp-fin"]}]}})
    client = app.test_client()
    token_endpoint.claims_extra = {"groups": ["GRP-FIN"]}
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert client.get("/f/finanzas/").status_code == 200

    # Al volver a entrar sin el grupo pierde el acceso
    client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    token_endpoint.claims_extra = {"groups": []}
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    assert client.get("/f/finanzas/").status_code == 404


def test_no_takeover_of_local_account(entra_app, token_endpoint):
    app = entra_app()
    add_user(app, "juan@contoso.com")
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    assert "/login" in finish_login(client, q["state"]).location
    assert client.get("/f/home/").status_code == 302


def test_disabled_entra_user(entra_app, token_endpoint):
    app = entra_app()
    add_user(app, "juan@contoso.com", password=None, source="entra", external_id="oid-juan")
    with app.app_context():
        conn = db.get_db()
        conn.execute("UPDATE users SET enabled = 0")
        conn.commit()
    client = app.test_client()
    _, q = start_login(client, token_endpoint)
    assert "/login" in finish_login(client, q["state"]).location


def test_single_logout(entra_app, token_endpoint):
    client = entra_app(single_logout=True).test_client()
    _, q = start_login(client, token_endpoint)
    finish_login(client, q["state"])
    resp = client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")})
    assert resp.location.startswith(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/logout")


def test_entra_disabled_routes(client):
    assert "/login" in client.get("/auth/entra/login").location
    assert "/login" in client.get("/auth/entra/callback").location


# --------------------------------------------------------------------------- endpoints propios


def test_custom_endpoints_generic_oidc(make_app, token_endpoint):
    app = make_app({"auth": {"entra": {
        "enabled": True, "client_id": CLIENT_ID, "client_secret": "s",
        "authorize_url": "https://idp.local/authorize", "token_url": "https://idp.local/token",
        "issuer": "https://idp.local"}}})
    client = app.test_client()
    url, q = start_login(client, token_endpoint)
    assert url.netloc == "idp.local"
    token_endpoint.claims_extra = {"iss": "https://idp.local", "tid": None}
    assert finish_login(client, q["state"]).location == "/"
    assert token_endpoint.calls[0]["url"] == "https://idp.local/token"


def test_multitenant_issuer_uses_tid(make_app, token_endpoint):
    app = make_app({"auth": {"entra": entra_cfg(tenant_id="organizations")}})
    client = app.test_client()
    token_endpoint.claims_extra = {"tid": "t-9", "iss": "https://login.microsoftonline.com/t-9/v2.0"}
    _, q = start_login(client, token_endpoint)
    assert finish_login(client, q["state"]).location == "/"


# --------------------------------------------------------------------------- validación unitaria


def test_decode_jwt_invalid():
    for bad in ["abc", "a.b", "a.!!!.c", f"x.{base64.urlsafe_b64encode(b'[1]').decode()}.y"]:
        with pytest.raises(SSOError):
            oauth2.decode_jwt_claims(bad)


def test_audience_list_requires_azp():
    cfg = entra_cfg()
    claims = base_claims("n", aud=[CLIENT_ID, "otra"])
    with pytest.raises(SSOError):
        oauth2.validate_id_token(make_jwt(claims), cfg, "n")
    claims["azp"] = CLIENT_ID
    assert oauth2.validate_id_token(make_jwt(claims), cfg, "n")["oid"] == "oid-juan"


# --------------------------------------------------------------------------- MSAL


class FakeMsal:
    claims: dict = {}

    def initiate_auth_code_flow(self, scopes, redirect_uri, prompt):
        assert "openid" not in scopes  # MSAL no admite scopes reservados
        return {"auth_uri": "https://login.microsoftonline.com/x/authorize?state=abc",
                "state": "abc", "redirect_uri": redirect_uri}

    def acquire_token_by_auth_code_flow(self, flow, args):
        if args.get("state") != flow["state"]:
            raise ValueError("state mismatch")
        return {"id_token_claims": dict(self.claims)}


def test_msal_provider(entra_app, monkeypatch):
    fake = FakeMsal()
    fake.claims = {"tid": TENANT, "oid": "o-msal", "preferred_username": "m@contoso.com"}
    monkeypatch.setattr(msal_provider, "_msal_app", lambda ecfg: fake)
    client = entra_app(provider="msal", scopes=["openid", "User.Read"]).test_client()
    resp = client.get("/auth/entra/login")
    assert resp.location.startswith("https://login.microsoftonline.com/")
    assert client.get("/auth/entra/callback?code=x&state=zzz").location.endswith("/login")
    client.get("/auth/entra/login")
    assert client.get("/auth/entra/callback?code=x&state=abc").location == "/"


def test_msal_unreachable(entra_app, monkeypatch):
    def boom(ecfg):
        raise ConnectionError("sin internet")
    monkeypatch.setattr(msal_provider, "_msal_app", boom)
    client = entra_app(provider="msal").test_client()
    resp = client.get("/auth/entra/login")
    assert "/login" in resp.location

"""Validación del id_token en el proveedor OAuth2 (sin red ni Flask)."""
import base64
import time

import pytest

from storageweb.providers import SSOError, get_sso_provider
from storageweb.providers.entra import oauth2
from storageweb.providers.entra.common import endpoints
from tests.sso_helpers import CLIENT_ID, TENANT, base_claims, entra_cfg, make_jwt


def test_decode_jwt_invalid():
    for bad in ["abc", "a.b", "a.!!!.c", f"x.{base64.urlsafe_b64encode(b'[1]').decode()}.y"]:
        with pytest.raises(SSOError):
            oauth2.decode_jwt_claims(bad)


def test_valid_token():
    claims = oauth2.validate_id_token(make_jwt(base_claims("n")), entra_cfg(), "n")
    assert claims["oid"] == "oid-juan"


@pytest.mark.parametrize("bad", [
    {"aud": "otra-app"},
    {"iss": "https://login.microsoftonline.com/otro/v2.0"},
    {"exp": int(time.time()) - 3600},
    {"exp": "nunca"},
    {"nbf": int(time.time()) + 3600},
    {"nonce": "otro"},
])
def test_invalid_claims(bad):
    with pytest.raises(SSOError):
        oauth2.validate_id_token(make_jwt(base_claims("n", **bad)), entra_cfg(), "n")


def test_clock_skew_tolerated():
    claims = base_claims("n", exp=int(time.time()) - oauth2.CLOCK_SKEW + 30)
    assert oauth2.validate_id_token(make_jwt(claims), entra_cfg(), "n")


def test_audience_list_requires_azp():
    cfg = entra_cfg()
    claims = base_claims("n", aud=[CLIENT_ID, "otra"])
    with pytest.raises(SSOError):
        oauth2.validate_id_token(make_jwt(claims), cfg, "n")
    claims["azp"] = CLIENT_ID
    assert oauth2.validate_id_token(make_jwt(claims), cfg, "n")["oid"] == "oid-juan"


def test_endpoints_from_tenant_and_overrides():
    ep = endpoints(entra_cfg())
    assert ep["authorize"] == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
    assert ep["token"].endswith("/oauth2/v2.0/token")
    custom = endpoints(entra_cfg(token_url="https://idp/token", issuer="https://idp"))
    assert custom["token"] == "https://idp/token" and custom["issuer"] == "https://idp"


def test_begin_builds_pkce_request():
    url, flow = get_sso_provider(entra_cfg()).begin("https://app/cb")
    assert flow["provider"] == "oauth2" and 43 <= len(flow["code_verifier"]) <= 128
    assert "code_challenge_method=S256" in url and f"state={flow['state']}" in url


def test_unknown_provider():
    with pytest.raises(SSOError):
        get_sso_provider(entra_cfg(), "saml")

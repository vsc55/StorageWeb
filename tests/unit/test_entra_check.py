"""Comprobación de la configuración de Entra ID (sin red: se simulan las respuestas de Microsoft)."""
import pytest

from storageweb.providers.entra import check as entra_check, directory as entra_directory, oauth2

ECFG = {"tenant_id": "t1", "client_id": "c1", "client_secret": "s", "timeout_seconds": 5}
REDIRECT = "https://files.example.com/auth/entra/callback"


@pytest.fixture
def fake(monkeypatch):
    """Configura qué devuelve cada URL: metadatos, authorize y token."""
    class Fake:
        metadata = (200, {}, "{}")
        authorize = (302, {"Location": REDIRECT + "?error=login_required"}, "")
        token = {"access_token": "x"}
        urls: list = []

    f = Fake()
    f.urls = []

    def http_get(url, timeout):
        f.urls.append(url)
        return f.metadata if "well-known" in url else f.authorize

    monkeypatch.setattr(entra_check, "_http_get", http_get)
    monkeypatch.setattr(oauth2, "_http_post", lambda url, data, timeout: f.token)
    f.groups = (True, "")
    monkeypatch.setattr(entra_directory, "can_read_groups", lambda token: f.groups)
    return f


def _by_key(results):
    return {r["key"]: r["ok"] for r in results}


def test_everything_ok(fake):
    results = entra_check.check(ECFG, REDIRECT)
    assert _by_key(results) == {"metadata": True, "client": True, "redirect": True, "secret": True, "groups": True}
    assert entra_check.summary(results) is True
    assert "prompt=none" in fake.urls[1] and "redirect_uri=https%3A%2F%2Ffiles" in fake.urls[1]


def test_unknown_tenant_stops(fake):
    fake.metadata = (400, {}, "AADSTS90002")
    results = entra_check.check(ECFG, REDIRECT)
    assert _by_key(results) == {"metadata": False} and entra_check.summary(results) is False


@pytest.mark.parametrize("body, expected", [
    ("AADSTS50011: The redirect URI does not match", {"client": True, "redirect": False}),
    ("AADSTS700016: Application not found", {"client": False}),
])
def test_authorize_errors(fake, body, expected):
    fake.authorize = (200, {}, body)
    results = _by_key(entra_check.check(ECFG, REDIRECT))
    assert {k: results[k] for k in expected} == expected


@pytest.mark.parametrize("description, ok", [
    ("AADSTS7000215: Invalid client secret provided.", False),
    ("AADSTS7000222: The provided client secret keys are expired.", False),
])
def test_secret_errors(fake, description, ok):
    fake.token = {"error": "invalid_client", "error_description": description}
    results = entra_check.check(ECFG, REDIRECT)
    assert _by_key(results)["secret"] is ok
    assert "caducado" in results[-1]["message"] or "no es válido" in results[-1]["message"]


def test_custom_endpoints_only_metadata(fake):
    cfg = {**ECFG, "authorize_url": "https://idp/auth", "token_url": "https://idp/token", "issuer": "https://idp"}
    results = entra_check.check(cfg, REDIRECT)
    assert fake.urls == ["https://idp/.well-known/openid-configuration"]
    assert entra_check.summary(results) is None


def test_network_error(monkeypatch):
    def boom(url, timeout):
        raise OSError("sin red")
    monkeypatch.setattr(entra_check, "_http_get", boom)
    results = entra_check.check(ECFG, REDIRECT)
    assert results[0]["ok"] is False and "sin red" in results[0]["message"]


def test_group_reading_missing(fake):
    fake.groups = (False, "Insufficient privileges to complete the operation.")
    results = entra_check.check(ECFG, REDIRECT)
    assert _by_key(results)["groups"] is False and entra_check.summary(results) is False
    assert "Insufficient privileges" in results[-1]["message"]

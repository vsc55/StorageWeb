"""Comprobación de la configuración de Entra ID (sin red: se simulan las respuestas de Microsoft)."""
import base64
import json

import pytest

from storageweb.providers.entra import check as entra_check, directory as entra_directory, oauth2

ECFG = {"tenant_id": "t1", "client_id": "c1", "client_secret": "s", "timeout_seconds": 5}
REDIRECT = "https://files.example.com/auth/entra/callback"


def _jwt(**claims):
    """Un token con esos claims (la comprobación no verifica la firma: solo mira qué permisos tiene)."""
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"h.{body}.s"


def _msg(results, key):
    return next(r["message"] for r in results if r["key"] == key)


@pytest.fixture
def fake(monkeypatch):
    """Configura qué devuelve cada URL: metadatos, authorize y token."""
    class Fake:
        metadata = (200, {}, "{}")
        authorize = (302, {"Location": REDIRECT + "?error=login_required"}, "")
        token = {"access_token": _jwt(roles=["Group.Read.All", "User.Read.All"])}
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
    f.users = (True, "")
    monkeypatch.setattr(entra_directory, "can_read_users", lambda token: f.users)
    return f


def _by_key(results):
    return {r["key"]: r["ok"] for r in results}


def test_everything_ok(fake):
    results = entra_check.check(ECFG, REDIRECT)
    assert _by_key(results) == {"metadata": True, "client": True, "redirect": True, "secret": True, "groups": True,
                                "users": True, "signin_scopes": None}  # nadie ha entrado todavía: informativo
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
    assert "caducado" in _msg(results, "secret") or "no es válido" in _msg(results, "secret")


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
    assert "Insufficient privileges" in _msg(results, "groups")


def test_new_secret_not_yet_active_is_pending_not_an_error(fake):
    """Microsoft tarda en activar un secreto recién creado: mientras tanto, «activándose», no «no es válido»."""
    fake.token = {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."}
    results = entra_check.check(ECFG, REDIRECT, secret_is_new=True)
    secret = next(r for r in results if r["key"] == "secret")
    assert secret["key"] == "secret" and secret["ok"] is None and secret.get("pending")
    assert entra_check.summary(results) is None  # ni bien ni mal todavía
    # Un secreto caducado sigue siendo un error aunque sea nuevo
    fake.token = {"error": "invalid_client", "error_description": "AADSTS7000222: expired"}
    assert _by_key(entra_check.check(ECFG, REDIRECT, secret_is_new=True))["secret"] is False


def test_every_application_permission_and_extra_ones(fake):
    """Cada permiso de aplicación que usa StorageWeb, si falta (reparable) y los que sobran (aviso)."""
    fake.token = {"access_token": _jwt(roles=[])}
    results = entra_check.check(ECFG, REDIRECT)
    groups = next(r for r in results if r["key"] == "groups")
    assert groups["ok"] is False and groups["fixable"] and "Group.Read.All" in groups["message"]
    assert entra_check.repairs(results) == {"new_secret": False}

    fake.token = {"access_token": _jwt(roles=["Group.Read.All", "Directory.ReadWrite.All", "Mail.Send"])}
    results = entra_check.check(ECFG, REDIRECT)
    assert _by_key(results)["groups"] is True
    extra = next(r for r in results if r["key"] == "extra_permissions")
    assert extra["ok"] is None and "Directory.ReadWrite.All, Mail.Send" in extra["message"]


def test_signin_permissions_from_the_last_signin(fake):
    cfg = {**ECFG, "scopes": ["User.Read"]}
    results = entra_check.check(cfg, REDIRECT)
    assert _by_key(results)["signin_scopes"] is None  # nadie ha entrado todavía
    last = {"at": "2026-11-15T00:43:00+00:00", "scopes": ["email", "openid", "profile", "User.Read"]}
    assert _by_key(entra_check.check(cfg, REDIRECT, last_signin=last))["signin_scopes"] is True
    last["scopes"] = ["openid", "profile"]
    results = entra_check.check(cfg, REDIRECT, last_signin=last)
    scopes = next(r for r in results if r["key"] == "signin_scopes")
    assert scopes["ok"] is False and scopes["fixable"] and "email, User.Read" in scopes["message"]


def test_signin_permissions_from_the_consent_given_by_storageweb(fake):
    """Una aplicación que registró (o reparó) StorageWeb ya tiene el consentimiento: sale en verde desde el principio."""
    cfg = {**ECFG, "scopes": ["User.Read"]}
    last = {"at": "2026-11-14T23:33:00+00:00", "scopes": ["User.Read", "email", "openid", "profile"],
            "source": "consent"}
    results = entra_check.check(cfg, REDIRECT, last_signin=last)
    scopes = next(r for r in results if r["key"] == "signin_scopes")
    assert scopes["ok"] is True and "registró o reparó" in scopes["message"]
    assert entra_check.summary(results) is True

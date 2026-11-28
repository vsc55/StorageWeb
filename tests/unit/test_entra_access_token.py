"""Los tokens de acceso de Microsoft que manda VS Code se comprueban de verdad: firma con las claves del tenant,
destinatario, emisor, tenant, caducidad, permiso y aplicación que lo pidió."""
from __future__ import annotations

import time

import pytest

from storageweb.providers.base import AuthDenied
from storageweb.providers.entra import access_token, register
from tests.entra_keys import OTHER_KEY, VSCODE, fake_microsoft, token
from tests.sso_helpers import CLIENT_ID, TENANT, entra_cfg


@pytest.fixture
def microsoft(monkeypatch):
    return fake_microsoft(monkeypatch)


def _denied(code: str, tok: str, section=None):
    with pytest.raises(AuthDenied) as exc:
        access_token.verify(section or entra_cfg(), tok)
    assert exc.value.code == code, exc.value.code


def test_a_good_token(microsoft):
    claims = access_token.verify(entra_cfg(), token())
    assert claims["oid"] == "oid-juan"
    assert microsoft == [f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys?appid={CLIENT_ID}"]
    access_token.verify(entra_cfg(), token())
    assert len(microsoft) == 1                                       # las claves, guardadas


def test_only_v2_tokens(microsoft):
    """En un token v1, aud es la URI que se pidió (api://…), que otra aplicación podría haber registrado con sus
    propios App Roles: solo v2, con el client id como aud."""
    _denied("version", token(aud=f"api://{CLIENT_ID}", iss=f"https://sts.windows.net/{TENANT}/", ver="1.0",
                             azp=None, appid=VSCODE))
    _denied("version", token(aud=f"api://{CLIENT_ID}"))
    _denied("version", token(ver="1.0"))
    _denied("version", token(ver=None))
    _denied("client", token(azp=None, appid=VSCODE))                  # appid es de v1


def test_personal_accounts_are_not_an_organization(microsoft):
    personal = access_token.CONSUMERS
    tok = token(tid=personal, iss=f"https://login.microsoftonline.com/{personal}/v2.0")
    _denied("tenant", tok, entra_cfg(tenant_id="organizations"))
    assert access_token.verify(entra_cfg(tenant_id="common"), tok)["tid"] == personal


def test_microsoft_unreachable_is_not_asked_again_at_once(monkeypatch):
    asked = []

    def down(method, url, **_kw):
        asked.append(url)
        raise register.RegisterError("timed out")
    monkeypatch.setattr(access_token, "_request", down)
    access_token.clear_cache()
    for _n in range(5):
        with pytest.raises(AuthDenied) as exc:
            access_token.verify(entra_cfg(), token())
        assert exc.value.code == "unavailable" and "timed out" not in exc.value.message   # sin el error de red
    assert len(asked) == 1                                           # una petición, no cinco hilos esperando


@pytest.mark.parametrize("change,code", [
    ({"key": OTHER_KEY}, "invalid_token"),                           # firmado por otro
    ({"alg": "HS256"}, "invalid_token"),
    ({"aud": "otra-aplicacion"}, "version"),
    ({"iss": "https://login.example.com/v2.0"}, "version"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"nbf": int(time.time()) + 3600}, "expired"),
    ({"scp": "User.Read"}, "invalid_token"),                         # no es para entrar en StorageWeb
    ({"azp": "otra-app-0000"}, "client"),                            # no lo pidió VS Code
    ({"tid": "99999999-2222-3333-4444-555555555555"}, "tenant"),     # otra organización
    ({"tid": "../../evil"}, "tenant"),                               # nunca en la dirección de las claves
])
def test_what_is_refused(microsoft, change, code):
    _denied(code, token(**change))


def test_not_a_jwt(microsoft):
    for bad in ("", "a.b", "no.es.base64!", "x" * 20_000):
        _denied("invalid_token", bad)
    assert microsoft == []                                           # sin preguntar a Microsoft


def test_an_unknown_key_asks_again_but_not_every_time(microsoft):
    _denied("invalid_token", token(kid="otra"))
    assert len(microsoft) == 1                                       # la primera vez, ya pidió las claves
    _denied("invalid_token", token(kid="otra"))
    assert len(microsoft) == 1                                       # como mucho cada 5 minutos


def test_multi_tenant_accepts_any_organization(microsoft):
    other = "99999999-2222-3333-4444-555555555555"
    section = entra_cfg(tenant_id="organizations")
    claims = access_token.verify(section, token(tid=other, iss=f"https://login.microsoftonline.com/{other}/v2.0"))
    assert claims["tid"] == other
    # Las claves, de common: nunca del tid del token (lo escribe quien lo manda, antes de mirar la firma)
    assert microsoft == [f"https://login.microsoftonline.com/common/discovery/v2.0/keys?appid={CLIENT_ID}"]
    for n in range(5):                                               # organizaciones inventadas: ni una petición más
        fake = f"9999999{n}-2222-3333-4444-555555555555"
        _denied("invalid_token", token(tid=fake, iss=f"https://login.microsoftonline.com/{fake}/v2.0", key=OTHER_KEY),
                section)
    assert len(microsoft) == 1


def test_odd_headers_and_keys_do_not_break(monkeypatch, microsoft):
    for kid in (["lista"], {"a": 1}, None, 7):
        _denied("invalid_token", token(kid=kid))
    monkeypatch.setattr(access_token, "_request", lambda method, url, **kw: (200, ["no", "es", "un", "dict"]))
    access_token.clear_cache()
    _denied("unavailable", token())


@pytest.mark.parametrize("answer", [(200, {}), (200, {"keys": []}), (200, {"keys": [{"kty": "EC", "kid": "x"}]}),
                                    (500, {"keys": [{"kty": "RSA", "kid": "x"}]})])
def test_an_answer_without_keys_is_a_failure_not_no_keys(monkeypatch, answer):
    """Un proxy que contesta 200 sin claves: si se guardara como «no hay claves», durante un día cada token auténtico
    sería invalid_token y contaría para el bloqueo de IPs (la de toda una oficina)."""
    asked = []
    monkeypatch.setattr(access_token, "_request", lambda method, url, **kw: asked.append(url) or answer)
    access_token.clear_cache()
    _denied("unavailable", token())
    _denied("unavailable", token())
    assert len(asked) == 1                                           # y no se vuelve a preguntar enseguida


def test_consumers_only_personal_accounts(microsoft):
    personal = access_token.CONSUMERS
    work = token()
    _denied("tenant", work, entra_cfg(tenant_id="consumers"))
    tok = token(tid=personal, iss=f"https://login.microsoftonline.com/{personal}/v2.0")
    assert access_token.verify(entra_cfg(tenant_id="consumers"), tok)["tid"] == personal


def test_a_key_for_another_issuer_is_not_valid_here(monkeypatch):
    from tests.entra_keys import jwks
    keys = jwks()
    keys["keys"][0]["issuer"] = "https://login.microsoftonline.com/99999999-2222-3333-4444-555555555555/v2.0"
    monkeypatch.setattr(access_token, "_request", lambda method, url, **kw: (200, keys))
    access_token.clear_cache()
    _denied("version", token())
    keys["keys"][0]["issuer"] = "https://login.microsoftonline.com/{tenantid}/v2.0"      # la de common
    access_token.clear_cache()
    assert access_token.verify(entra_cfg(), token())["tid"] == TENANT


def test_the_registration_exposes_the_api_once(monkeypatch):
    calls = []
    monkeypatch.setattr(register, "_graph", lambda method, path, tok, body=None, ok=None: calls.append((method, body)) or {})
    app = {"id": "obj-1", "appId": CLIENT_ID}
    done = register.expose_desktop_api("tok", app)
    assert len(done) == 3 and [c[0] for c in calls] == ["PATCH"] * 3
    scope = calls[1][1]["api"]["oauth2PermissionScopes"][0]
    assert calls[0][1] == {"identifierUris": [f"api://{CLIENT_ID}"]}
    assert scope["value"] == "access_as_user" and calls[1][1]["api"]["requestedAccessTokenVersion"] == 2
    assert calls[2][1]["api"]["preAuthorizedApplications"] == [{"appId": VSCODE, "delegatedPermissionIds": [scope["id"]]}]
    calls.clear()
    ready = {**app, "identifierUris": [f"api://{CLIENT_ID}"],
             "api": {"requestedAccessTokenVersion": 2, "oauth2PermissionScopes": [scope],
                     "preAuthorizedApplications": [{"appId": VSCODE, "delegatedPermissionIds": [scope["id"]]}]}}
    assert register.expose_desktop_api("tok", ready) == [] and calls == []      # ya estaba: no toca nada

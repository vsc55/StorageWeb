"""Fixtures de los tests de integración (aplicación Flask completa)."""
import pytest

from storageweb.providers import oauth2
from tests.sso_helpers import base_claims, entra_cfg, make_jwt


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

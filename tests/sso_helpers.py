"""Utilidades para simular Entra ID en los tests (id_token sin firma, flujo de login)."""
import base64
import json
import time
from urllib.parse import parse_qs, urlparse

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

"""Un Microsoft de mentira que firma de verdad: una clave RSA de prueba, sus claves públicas (JWKS) como las da
``/discovery/v2.0/keys`` y tokens de acceso RS256 para la API de StorageWeb (entrar desde VS Code con la cuenta de
Windows, ``providers/entra/access_token.py``)."""
from __future__ import annotations

import base64
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tests.sso_helpers import CLIENT_ID, TENANT

VSCODE = "aebc6443-996d-45c2-90f0-388ff96faa56"
KID = "clave-de-prueba"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int(value: int) -> str:
    return _b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def jwks() -> dict:
    numbers = _KEY.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "use": "sig", "kid": KID, "n": _int(numbers.n), "e": _int(numbers.e)}]}


def claims(**extra) -> dict:
    """Los de un token de acceso v2 de Microsoft para StorageWeb pedido por VS Code."""
    now = int(time.time())
    found = {"aud": CLIENT_ID, "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT,
             "iat": now, "nbf": now, "exp": now + 3600, "oid": "oid-juan", "preferred_username": "Juan@Contoso.com",
             "name": "Juan Pérez", "scp": "access_as_user", "azp": VSCODE, "ver": "2.0"}
    found.update(extra)
    return found


def token(*, kid: str = KID, alg: str = "RS256", key=None, **extra) -> str:
    """Un token firmado con la clave de prueba (``key=…OTHER`` para una firma que no corresponde)."""
    head = _b64(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    body = _b64(json.dumps(claims(**extra)).encode())
    signature = (key or _KEY).sign(f"{head}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{_b64(signature)}"


OTHER_KEY = _OTHER


def fake_microsoft(monkeypatch) -> list:
    """Las claves públicas salen de aquí, no de internet; devuelve la lista de direcciones pedidas."""
    from storageweb.providers.entra import access_token
    asked: list = []

    def request(method, url, **_kw):
        asked.append(url)
        return 200, jwks()
    monkeypatch.setattr(access_token, "_request", request)
    access_token.clear_cache()
    return asked


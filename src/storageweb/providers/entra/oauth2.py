"""Proveedor OAuth2/OpenID Connect implementado con la librería estándar.

Authorization Code + PKCE (S256). No hace descubrimiento (``.well-known``) ni descarga
metadatos al arrancar: las URLs se calculan a partir del tenant de Entra ID o se configuran
explícitamente (válido para cualquier proveedor OIDC). Solo hay tráfico de red al canjear el
código por el token, durante el login.
"""
from __future__ import annotations

import binascii
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from ..base import BASE_SCOPES, SSOError
from .common import MS_LOGIN, MULTI_TENANT, EntraProvider, endpoints
from ...text import b64url_decode, pkce_challenge

CLOCK_SKEW = 300    # segundos de tolerancia en exp/nbf
FLOW_MAX_AGE = 600  # el usuario tiene 10 min para completar el login


GRANTED_KEY = "_storageweb_granted_scopes"


def scopes_for(ecfg: dict) -> list[str]:
    out = list(BASE_SCOPES)
    for scope in ecfg.get("scopes", []):
        if scope not in out:
            out.append(scope)
    return out


def _http_post(url: str, data: dict, timeout: float) -> dict:
    """POST x-www-form-urlencoded; devuelve el JSON. Respeta HTTPS_PROXY / NO_PROXY."""
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL de config)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Entra devuelve 400/401 con {"error": ..., "error_description": ...}
        try:
            return json.loads(exc.read().decode("utf-8"))
        except ValueError:
            raise SSOError("http_error", f"HTTP {exc.code} del endpoint de token") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SSOError("network_error", f"No se pudo contactar con el proveedor: {exc}") from exc
    except ValueError as exc:
        raise SSOError("invalid_response", "Respuesta no JSON del endpoint de token") from exc


def decode_jwt_claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise SSOError("invalid_id_token", "Formato JWT incorrecto")
    try:
        claims = json.loads(b64url_decode(parts[1]))
    except (ValueError, binascii.Error) as exc:
        raise SSOError("invalid_id_token", "No se pudo decodificar el JWT") from exc
    if not isinstance(claims, dict):
        raise SSOError("invalid_id_token", "Payload JWT no válido")
    return claims


def validate_id_token(id_token: str, ecfg: dict, nonce: str) -> dict:
    """Valida iss, aud, azp, exp, nbf y nonce del id_token.

    La firma no se comprueba: el token llega directamente del endpoint de token por TLS y
    autenticándonos con el client_secret, caso que OpenID Connect Core 1.0 §3.1.3.7 permite.
    """
    claims = decode_jwt_claims(id_token)
    now = time.time()

    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if ecfg["client_id"] not in audiences:
        raise SSOError("invalid_audience", "El token no es para esta aplicación")
    if len(audiences) > 1 and claims.get("azp") != ecfg["client_id"]:
        raise SSOError("invalid_audience", "azp no coincide")

    try:
        exp = float(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SSOError("invalid_id_token", "Falta exp") from exc
    if exp < now - CLOCK_SKEW:
        raise SSOError("token_expired", "El token ha caducado")
    if float(claims.get("nbf", 0) or 0) > now + CLOCK_SKEW:
        raise SSOError("token_not_yet_valid", "El token aún no es válido")

    if not nonce or not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SSOError("invalid_nonce", "nonce no coincide")

    tenant = (ecfg.get("tenant_id") or "").lower()
    if ecfg.get("issuer"):
        expected_iss = ecfg["issuer"]
    elif tenant in MULTI_TENANT:
        expected_iss = f"{MS_LOGIN}/{claims.get('tid', '')}/v2.0"
    else:
        expected_iss = endpoints(ecfg)["issuer"]
    if claims.get("iss") != expected_iss:
        raise SSOError("invalid_issuer", f"Emisor inesperado: {claims.get('iss')}")
    return claims


class OAuth2Provider(EntraProvider):
    name = "oauth2"

    def begin(self, redirect_uri: str) -> tuple[str, dict]:
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)  # 86 caracteres (RFC 7636: 43-128)
        challenge = pkce_challenge(verifier)
        params = {
            "client_id": self.cfg["client_id"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(scopes_for(self.cfg)),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        url = f"{endpoints(self.cfg)['authorize']}?{urllib.parse.urlencode(params)}"
        flow = {"provider": self.name, "state": state, "nonce": nonce, "code_verifier": verifier,
                "redirect_uri": redirect_uri, "created": int(time.time())}
        return url, flow

    def complete(self, flow: dict, args: dict) -> dict:
        if not hmac.compare_digest(str(args.get("state", "")), str(flow.get("state", ""))):
            raise SSOError("invalid_state", "state no coincide")
        if time.time() - flow.get("created", 0) > FLOW_MAX_AGE:
            raise SSOError("flow_expired", "El inicio de sesión ha caducado")
        if args.get("error"):
            raise SSOError(args["error"], args.get("error_description", ""))
        code = args.get("code")
        if not code:
            raise SSOError("missing_code", "No se recibió el código de autorización")

        token = _http_post(endpoints(self.cfg)["token"], {
            "grant_type": "authorization_code",
            "client_id": self.cfg["client_id"],
            "client_secret": self.cfg["client_secret"],
            "code": code,
            "redirect_uri": flow["redirect_uri"],
            "code_verifier": flow["code_verifier"],
            "scope": " ".join(scopes_for(self.cfg)),
        }, float(self.cfg.get("timeout_seconds", 15)))
        if "error" in token:
            raise SSOError(str(token["error"]), str(token.get("error_description", "")))
        id_token = token.get("id_token")
        if not id_token:
            raise SSOError("missing_id_token", "El proveedor no devolvió id_token (¿falta el scope openid?)")
        claims = validate_id_token(id_token, self.cfg, flow["nonce"])
        return {**claims, GRANTED_KEY: token.get("scope")}  # los permisos concedidos (no es un claim del token)

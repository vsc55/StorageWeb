"""Tokens de acceso de Microsoft para la API de StorageWeb (entrar desde una aplicación de escritorio con la cuenta
de Windows): comprobarlos de verdad, con su firma.

La extensión de VS Code pide a Windows (WAM, a través del proveedor ``microsoft`` de VS Code) un token para
``api://<client_id>/access_as_user`` y lo canjea en ``/connect/desktop`` por un token de API de StorageWeb.
A diferencia del id_token del inicio de sesión web (ADR 0004: lo pide el propio servidor por TLS), este token llega
del cliente, así que **se comprueba la firma** con las claves públicas del tenant (JWKS) y además: algoritmo RS256,
``aud`` (la aplicación de StorageWeb), ``iss`` y ``tid`` (el tenant), ``exp``/``nbf`` (5 minutos de margen), el
permiso ``access_as_user`` en ``scp`` y que lo pidió una aplicación autorizada (``azp``: VS Code). Solo
tokens v2 (``ver`` 2.0, ``aud`` = el client id).
Solo la nube pública de Microsoft (``login.microsoftonline.com``).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ...i18n import _
from ...text import b64url_decode
from ..base import AuthDenied
from .common import MS_LOGIN, MULTI_TENANT
from .register import RegisterError, _request

SCOPE = "access_as_user"                                   # el permiso que expone la aplicación de StorageWeb
VSCODE_CLIENT_ID = "aebc6443-996d-45c2-90f0-388ff96faa56"  # la aplicación de VS Code (autorizada en su API)
CLIENT_APPS = frozenset({VSCODE_CLIENT_ID})               # las que pueden pedir el token
SKEW = 300
KEYS_TTL = 24 * 3600
REFRESH_EVERY = 300          # una clave desconocida vuelve a pedir las claves, como mucho cada 5 minutos
RETRY_AFTER = 60             # si Microsoft no contesta, no se vuelve a preguntar hasta pasado este tiempo
KEYS_TIMEOUT = 5             # segundos: mientras se piden, las demás peticiones que necesitan las claves esperan
CONSUMERS = "9188040d-6c67-4c5b-b112-36a304b66dad"   # el tenant de las cuentas personales de Microsoft

_log = logging.getLogger(__name__)
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_lock = threading.Lock()
_fetching = threading.Lock()                      # una sola descarga de claves a la vez
_keys: dict[str, tuple[float, dict]] = {}        # dirección → (cuándo se pidieron, {kid: jwk})
_failed: dict[str, float] = {}                    # dirección → cuándo falló la última vez


def scopes(section: dict) -> list[str]:
    """Lo que tiene que pedir la aplicación de escritorio para StorageWeb."""
    return [f"api://{section['client_id']}/{SCOPE}"]


def _denied(code: str = "invalid_token") -> AuthDenied:
    return AuthDenied(_("The Microsoft token is not valid for this StorageWeb."), code)


def _keys_url(section: dict) -> str:
    """De dónde salen las claves: del tenant configurado o, multi-tenant, de ``common`` (las mismas con las que
    Microsoft firma los tokens de todas las organizaciones). Nunca del ``tid`` del token: lo escribe quien lo manda
    (antes de comprobar la firma), y cada tenant inventado sería una petición a Microsoft y una entrada más aquí.
    Con ``appid``: si la aplicación tiene claves de firma propias (claims mapping), Microsoft firma con ellas y solo
    salen así; si no, son las de siempre."""
    tenant = str(section.get("tenant_id") or "").lower()
    where = "common" if tenant in MULTI_TENANT else tenant
    return f"{MS_LOGIN}/{where}/discovery/v2.0/keys?appid={section['client_id']}"


def _cached(url: str, refresh: bool) -> dict | None:
    """Las claves guardadas si todavía valen (``refresh``: si no se pidieron hace menos de ``REFRESH_EVERY``)."""
    with _lock:
        cached = _keys.get(url)
    if cached is None:
        return None
    age = time.monotonic() - cached[0]
    return cached[1] if age < (REFRESH_EVERY if refresh else KEYS_TTL) else None


def _unavailable() -> AuthDenied:
    return AuthDenied(_("Microsoft could not be reached to check the token. Try again in a while."), "unavailable")


def _jwks(url: str, *, refresh: bool = False) -> dict:
    """``{kid: jwk}`` de la dirección de claves ``url`` (:func:`_keys_url`), guardadas un día. Sin autenticar,
    cualquiera puede llegar aquí: una sola descarga a la vez (las demás esperan y usan su resultado), con un timeout
    corto y, si Microsoft no contesta o no da ninguna clave, ``RETRY_AFTER`` segundos sin volver a preguntar (cada
    petición ocuparía un hilo hasta el timeout). Una respuesta sin claves es un fallo, no «no hay claves»: si no,
    durante un día cada token auténtico sería ``invalid_token`` y contaría para el bloqueo de IPs."""
    keys = _cached(url, refresh)
    if keys is not None:
        return keys
    with _fetching:
        keys = _cached(url, refresh)               # la trajo otra petición mientras esta esperaba
        if keys is not None:
            return keys
        with _lock:
            failed = _failed.get(url)
        if failed is not None and time.monotonic() - failed < RETRY_AFTER:
            raise _unavailable()
        try:
            status, data = _request("GET", url, timeout=KEYS_TIMEOUT)
        except RegisterError as exc:
            status, data = 0, str(exc)
        found = data.get("keys") if status == 200 and isinstance(data, dict) else None
        keys = {k["kid"]: k for k in found if isinstance(k, dict) and isinstance(k.get("kid"), str)
                and k.get("kty") == "RSA"} if isinstance(found, list) else {}
        if not keys:
            _log.warning("Microsoft signing keys could not be read from %s: %s", url,
                         status if status != 200 else "no keys")
            with _lock:
                _failed[url] = time.monotonic()
            raise _unavailable()
        with _lock:
            _keys[url] = (time.monotonic(), keys)
            _failed.pop(url, None)
        return keys


def _public_key(jwk: dict):
    n = int.from_bytes(b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(b64url_decode(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _tenant_allowed(tenant: str, tid: str) -> bool:
    """Si una cuenta del tenant ``tid`` (un GUID) puede entrar con ``tenant_id`` = ``tenant``. Como las direcciones
    de la web: ``organizations`` sin las cuentas personales, ``consumers`` solo ellas, ``common`` todas."""
    if not _GUID.match(tid):
        return False
    if tenant == "organizations":
        return tid != CONSUMERS
    if tenant == "consumers":
        return tid == CONSUMERS
    return tenant == "common" or tid == tenant


def verify(section: dict, token: str) -> dict:
    """Los claims de ``token`` si es un token de acceso de Microsoft para esta StorageWeb, válido ahora y firmado
    por Microsoft; :class:`AuthDenied` (código ``invalid_token``) si no."""
    parts = str(token or "").split(".")
    if len(parts) != 3 or len(token) > 16_000:
        raise _denied()
    try:
        header = json.loads(b64url_decode(parts[0]))
        claims = json.loads(b64url_decode(parts[1]))
        signature = b64url_decode(parts[2])
    except (ValueError, TypeError) as exc:
        raise _denied() from exc
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "RS256" \
            or not isinstance(header.get("kid"), str):
        raise _denied()
    # Primero la firma (las claves no dependen de nada del token): lo que no firmó Microsoft es siempre
    # invalid_token, lo único que cuenta para el bloqueo de IPs; el resto de rechazos son de tokens auténticos
    where, kid = _keys_url(section), header["kid"]
    jwk = _jwks(where).get(kid) or _jwks(where, refresh=True).get(kid)
    if jwk is None:
        raise _denied()
    try:
        _public_key(jwk).verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"), padding.PKCS1v15(),
                                hashes.SHA256())
    except (InvalidSignature, ValueError, KeyError) as exc:
        raise _denied() from exc
    tenant = str(section.get("tenant_id") or "").lower()
    tid = str(claims.get("tid") or "").lower()
    if not _tenant_allowed(tenant, tid):
        raise AuthDenied(_("Your account does not belong to the allowed organization."), "tenant")
    # Solo tokens v2 (la API se expone con requestedAccessTokenVersion 2): su aud es el client id. En los v1 es la
    # URI que se pidió (api://…), que podría haber registrado otra aplicación con sus propios App Roles
    issuer = f"{MS_LOGIN}/{tid}/v2.0"
    if claims.get("ver") != "2.0" or claims.get("aud") != section["client_id"] or claims.get("iss") != issuer:
        raise _denied("version")
    # Cada clave dice para qué emisor firma ({tenantid} en las de common): una clave de otro emisor no vale aquí
    if "issuer" in jwk and str(jwk["issuer"]).replace("{tenantid}", tid) != issuer:
        raise _denied("version")
    now = time.time()
    try:
        if float(claims["exp"]) < now - SKEW or float(claims.get("nbf", 0)) > now + SKEW:
            raise _denied("expired")
    except (KeyError, TypeError, ValueError) as exc:
        raise _denied() from exc
    if SCOPE not in str(claims.get("scp") or "").split():
        raise _denied()
    if claims.get("azp") not in CLIENT_APPS:
        raise _denied("client")
    return claims


def clear_cache() -> None:
    with _lock:
        _keys.clear()
        _failed.clear()

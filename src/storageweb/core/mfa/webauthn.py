"""Las ceremonias WebAuthn (passkeys): registro y autenticación, verificadas aquí y en ningún otro sitio.

Puro: recibe lo que manda el navegador y lo que el servidor ya sabe (el challenge que emitió, el RP ID con el que
sirve, el origen que espera) y contesta qué es verdad de ello. Sin Flask, sin base de datos y sin reloj, así que cada
comprobación es un test y no un comentario. Basado en el de ServiceSentry (mismo autor).

**Qué se comprueba, y por qué ninguna es opcional**

* **el challenge**, en tiempo constante, contra el que emitió ESTE servidor: sin él, una aserción capturada una vez
  valdría para siempre.
* **el tipo de ceremonia**: una respuesta de registro repetida en el inicio de sesión no puede ser un inicio de sesión.
* **el origen**, exacto (igualdad de cadenas): ``https://archivos.ejemplo.com.atacante.net`` pasa cualquier prueba
  que no lo sea.
* **el hash del RP ID** dentro de los datos del autenticador, contra el SHA-256 del dominio con el que sirve
  StorageWeb: el navegador ata la credencial a él y aquí se comprueba que la ató al mismo sitio.
* **la presencia del usuario** (flag UP): una credencial que se usa sin que nadie toque nada es un fichero, no un
  factor.
* **el contador de firmas**, cuando el autenticador lleva uno: si no avanza, dos dispositivos responden por la misma
  credencial (la única señal del protocolo de que se ha clonado).

**Lo que NO se comprueba a propósito: la attestation.** Dice de qué modelo es el autenticador, y verificarla obliga a
mantener una lista de raíces de fabricantes para contestar algo que aquí no se pregunta: el segundo factor es «algo
que la persona tiene», no «algo de un fabricante aprobado». Se lee el formato solo para sacar la clave.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import struct
from urllib.parse import urlsplit

from . import cbor, cose

# Flags de los datos del autenticador (WebAuthn §6.1)
FLAG_UP = 0x01          # presente: alguien la tocó
FLAG_UV = 0x04          # verificado: PIN, huella o cara, no solo un toque
FLAG_AT = 0x40          # trae los datos de la credencial (registro)
FLAG_ED = 0x80          # trae extensiones (un mapa CBOR al final)

_DEFAULT_PORTS = {"https": 443, "http": 80}

CHALLENGE_BYTES = 32


class CeremonyError(ValueError):
    """La ceremonia no se sostiene. Una sola excepción y sin detalle hacia fuera: qué comprobación falló va a la
    auditoría, no a quien mandó la respuesta («origen equivocado» y «challenge equivocado» son dos pistas distintas
    para quien está probando)."""


def b64u_encode(raw: bytes) -> str:
    """base64url sin relleno: como WebAuthn pone los bytes en JSON."""
    return base64.urlsafe_b64encode(bytes(raw)).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    """base64url a bytes; ``b""`` para lo que no lo sea (nunca lanza: todo llega del navegador)."""
    s = str(text or "")
    s += "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s)
    except Exception:  # noqa: BLE001
        return b""


def new_challenge() -> str:
    return b64u_encode(secrets.token_bytes(CHALLENGE_BYTES))


def scope_from(public_url: str) -> tuple[str, str]:
    """``(rp_id, origen)`` de la dirección pública declarada (``network.public_url``), o ``("", "")`` si no sirve.

    Del valor declarado y NO de la petición, que detrás de un proxy es lo que diga el proxy: una credencial queda
    atada a su dominio y **no se puede mover**, así que adivinarlo daría llaves que un día dejan de valer sin
    explicación. Una IP no es un dominio registrable (WebAuthn no la admite), y sin HTTPS el navegador no deja usar
    passkeys salvo en ``localhost``."""
    text = str(public_url or "").strip().rstrip("/")
    if not text:
        return "", ""
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return "", ""
    try:
        ipaddress.ip_address(host)
        return "", ""
    except ValueError:
        pass
    scheme = parts.scheme.lower()
    if scheme != "https" and host != "localhost":
        return "", ""
    try:
        port = parts.port
    except ValueError:
        return "", ""
    # El navegador serializa el origen sin el puerto por defecto (``https://x`` y no ``https://x:443``): con él, la
    # igualdad exacta de :func:`_client_data` no casaría nunca y las passkeys no funcionarían sin decir por qué
    suffix = f":{port}" if port is not None and port != _DEFAULT_PORTS.get(scheme) else ""
    return host, f"{scheme}://{host}{suffix}"


def _extensions_to_the_end(data: bytes, at: int, flags: int) -> None:
    """Lo que queda desde ``at``: nada, o (con el flag ED) un único mapa CBOR que llega justo al final. Cualquier
    otra cosa son bytes que nadie declaró, y un lector que los ignora no distingue unos datos de unos datos con algo
    pegado."""
    if not flags & FLAG_ED:
        if at != len(data):
            raise CeremonyError("trailing bytes in authenticator data")
        return
    try:
        ext, consumed = cbor.decode_from(data, at)
    except cbor.CborError as exc:
        raise CeremonyError("extensions are not readable") from exc
    if not isinstance(ext, dict) or at + consumed != len(data):
        raise CeremonyError("extensions are not a single map")


def parse_auth_data(blob: bytes) -> dict:
    """Los datos del autenticador: cabecera fija de 37 bytes (hash del RP ID, flags, contador) y, si el flag AT lo
    dice, la credencial: AAGUID, id y la clave pública en CBOR (seguida de las extensiones si el flag ED lo dice, por
    eso el decodificador dice dónde acabó). Nada más: sin el flag ED, un byte de más es un error."""
    data = bytes(blob or b"")
    if len(data) < 37:
        raise CeremonyError("authenticator data too short")
    out = {"rp_id_hash": data[:32], "flags": data[32], "sign_count": struct.unpack(">I", data[33:37])[0],
           "credential_id": b"", "public_key": None, "public_key_raw": b"", "aaguid": b""}
    if not out["flags"] & FLAG_AT:
        _extensions_to_the_end(data, 37, out["flags"])
        return out
    if len(data) < 55:
        raise CeremonyError("attested credential data truncated")
    out["aaguid"] = data[37:53]
    cred_len = struct.unpack(">H", data[53:55])[0]
    if cred_len > 1023 or len(data) < 55 + cred_len:     # la especificación limita el id a 1023 bytes
        raise CeremonyError("credential id length is not usable")
    out["credential_id"] = data[55:55 + cred_len]
    key_at = 55 + cred_len
    try:
        key, consumed = cbor.decode_from(data, key_at)
    except cbor.CborError as exc:
        raise CeremonyError("credential public key is not readable") from exc
    if not isinstance(key, dict):
        raise CeremonyError("credential public key is not a COSE key")
    out["public_key"] = key
    # Los bytes de la clave tal como llegaron: se guardan así y los vuelve a leer este mismo decodificador cuando
    # llega una aserción (una sola representación, ningún segundo sitio que pueda discrepar)
    # (``consumed`` es una LONGITUD desde key_at, no la posición final)
    out["public_key_raw"] = data[key_at:key_at + consumed]
    _extensions_to_the_end(data, key_at + consumed, out["flags"])
    return out


def _client_data(raw: bytes, want_type: str, challenge: str, origin: str) -> dict:
    try:
        data = json.loads(bytes(raw or b"").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CeremonyError("client data is not JSON") from exc
    if not isinstance(data, dict):
        raise CeremonyError("client data is not an object")
    if str(data.get("type") or "") != want_type:
        raise CeremonyError("wrong ceremony type")
    got = str(data.get("challenge") or "")
    if not challenge or not hmac.compare_digest(got.encode("utf-8"), str(challenge).encode("utf-8")):
        raise CeremonyError("challenge does not match")
    if not origin or str(data.get("origin") or "") != origin:
        raise CeremonyError("origin does not match")
    return data


def _rp_and_presence(auth: dict, rp_id: str, require_uv: bool) -> None:
    if not hmac.compare_digest(auth["rp_id_hash"], hashlib.sha256(str(rp_id).encode()).digest()):
        raise CeremonyError("this credential was scoped to a different site")
    if not auth["flags"] & FLAG_UP:
        raise CeremonyError("nobody was present")
    if require_uv and not auth["flags"] & FLAG_UV:
        raise CeremonyError("user verification was required and did not happen")


def verify_registration(*, attestation_object: bytes, client_data_json: bytes, challenge: str, rp_id: str,
                        origin: str, require_uv: bool = False) -> dict:
    """Una respuesta de registro → la credencial que guardar, o :class:`CeremonyError`:
    ``{credential_id, public_key, public_key_raw, alg, sign_count, aaguid, uv}``. El algoritmo se fija AQUÍ."""
    _client_data(client_data_json, "webauthn.create", challenge, origin)
    try:
        att = cbor.decode(bytes(attestation_object or b""))
    except cbor.CborError as exc:
        raise CeremonyError("attestation object is not readable") from exc
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise CeremonyError("attestation object has no authenticator data")
    auth = parse_auth_data(att["authData"])
    _rp_and_presence(auth, rp_id, require_uv)
    if not auth["credential_id"] or auth["public_key"] is None:
        raise CeremonyError("no credential was attested")
    alg = cose.algorithm_of(auth["public_key"])
    if alg not in cose.SUPPORTED:
        raise CeremonyError("unsupported key algorithm")
    try:
        cose.public_key(auth["public_key"], alg)   # una clave que no se puede usar se rechaza ya, no al entrar
    except cose.CoseError as exc:
        raise CeremonyError("credential public key is not usable") from exc
    return {"credential_id": auth["credential_id"], "public_key": auth["public_key"],
            "public_key_raw": auth["public_key_raw"], "alg": alg, "sign_count": auth["sign_count"],
            "aaguid": auth["aaguid"], "uv": bool(auth["flags"] & FLAG_UV)}


def verify_assertion(*, auth_data: bytes, client_data_json: bytes, signature: bytes, challenge: str, rp_id: str,
                     origin: str, public_key: dict, alg: int, last_sign_count: int = 0,
                     require_uv: bool = False) -> dict:
    """Una respuesta de autenticación → ``{sign_count, uv}``, o :class:`CeremonyError`. La firma cubre los datos del
    autenticador seguidos del SHA-256 de los datos del cliente (donde están el challenge y el origen)."""
    _client_data(client_data_json, "webauthn.get", challenge, origin)
    auth = parse_auth_data(auth_data)
    _rp_and_presence(auth, rp_id, require_uv)
    signed = bytes(auth_data) + hashlib.sha256(bytes(client_data_json or b"")).digest()
    if not cose.verify(public_key, int(alg), bytes(signature or b""), signed):
        raise CeremonyError("signature does not verify")
    count, last = auth["sign_count"], int(last_sign_count or 0)
    # WebAuthn §7.2, paso 21: si el guardado es distinto de cero, el nuevo tiene que ser MAYOR. Cero guardado = el
    # autenticador no lleva contador (lo normal en los de plataforma) y no se le acusa de nada. Pero un cero que
    # llega cuando ya había contador también es no avanzar: aceptarlo dejaría que una clave clonada mandara 0,
    # bajara el guardado a 0 y apagara la comprobación para siempre (la del original y la suya)
    if last and count <= last:
        raise CeremonyError("the signature counter went backwards")
    return {"sign_count": count, "uv": bool(auth["flags"] & FLAG_UV)}


def rp_id_from(public_url: str) -> str:
    """El RP ID (dominio de las passkeys) de la dirección pública, o ``""`` si no sirve."""
    return scope_from(public_url)[0]


def origin_from(public_url: str) -> str:
    """El origen exacto que mandará el navegador (con el puerto), o ``""``."""
    return scope_from(public_url)[1]

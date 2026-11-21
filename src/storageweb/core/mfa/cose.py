"""Una clave COSE (RFC 8152) convertida en algo con lo que ``cryptography`` puede verificar una firma.

El autenticador entrega su clave pública como un mapa CBOR de etiquetas enteras. Esto la convierte en un objeto
clave y nada más: no verifica nada por su cuenta ni decide qué es aceptable (eso es de la ceremonia, que tiene la
firma y los datos firmados). Basado en el de ServiceSentry (mismo autor).

**El algoritmo sale de lo que se registró, no de la clave cuando llega la aserción.** Una clave COSE trae su propio
``alg``, y fiarse de él al autenticar dejaría a quien presenta la aserción elegir con qué se comprueba: el fallo del
``alg`` de JWT con otras palabras. Se guarda al registrar y se pasa de vuelta; una clave cuyo ``alg`` no coincide se
rechaza.

Tres algoritmos, los que llevan los autenticadores de verdad: **ES256** (``-7``, ECDSA P-256: todas las llaves y
autenticadores de plataforma), **RS256** (``-257``, RSASSA-PKCS1-v1_5: Windows Hello durante años) y **EdDSA**
(``-8``, Ed25519). Cualquier otro se rechaza: una firma que no se puede comprobar sería una que se acepta a ciegas.
"""
from __future__ import annotations

# Etiquetas comunes de una clave COSE (RFC 8152 §7.1) y las de cada familia (§13)
_KTY, _ALG = 1, 3
_CRV, _X, _Y = -1, -2, -3            # OKP / EC2
_N, _E = -1, -2                      # RSA (mismas etiquetas, otra familia)

KTY_OKP, KTY_EC2, KTY_RSA = 1, 2, 3
CRV_P256, CRV_ED25519 = 1, 6

ES256, EdDSA, RS256 = -7, -8, -257
SUPPORTED = (ES256, EdDSA, RS256)    # también el orden de preferencia que se ofrece al navegador


class CoseError(ValueError):
    """No es una clave con la que se pueda verificar: mal formada o de un algoritmo que no se admite."""


def algorithm_of(key: dict) -> int:
    """El ``alg`` que declara la clave, o 0. Se lee AL REGISTRAR y se guarda; nunca decide cómo se comprueba una
    aserción después."""
    try:
        return int((key or {}).get(_ALG) or 0)
    except (TypeError, ValueError):
        return 0


def public_key(key: dict, expect_alg: int):
    """El objeto clave pública de ``cryptography`` para ``key``, o :class:`CoseError`. ``expect_alg`` es el que se
    guardó al registrar; si la clave dice otro, se rechaza (o se buscó la credencial equivocada o alguien está
    eligiendo el algoritmo)."""
    if not isinstance(key, dict):
        raise CoseError("not a COSE key")
    alg = int(expect_alg or 0)
    if alg not in SUPPORTED:
        raise CoseError("unsupported algorithm")
    declared = algorithm_of(key)
    if declared and declared != alg:
        raise CoseError("key algorithm does not match the one registered")
    kty = key.get(_KTY)

    if alg == ES256:
        if kty != KTY_EC2 or key.get(_CRV) != CRV_P256:
            raise CoseError("ES256 needs an EC2 key on P-256")
        x, y = key.get(_X), key.get(_Y)
        if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
            raise CoseError("malformed P-256 coordinates")
        from cryptography.hazmat.primitives.asymmetric import ec   # noqa: PLC0415
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                             ec.SECP256R1()).public_key()

    if alg == EdDSA:
        if kty != KTY_OKP or key.get(_CRV) != CRV_ED25519:
            raise CoseError("EdDSA needs an OKP key on Ed25519")
        x = key.get(_X)
        if not isinstance(x, bytes) or len(x) != 32:
            raise CoseError("malformed Ed25519 point")
        from cryptography.hazmat.primitives.asymmetric import ed25519   # noqa: PLC0415
        return ed25519.Ed25519PublicKey.from_public_bytes(x)

    # RS256
    if kty != KTY_RSA:
        raise CoseError("RS256 needs an RSA key")
    n, e = key.get(_N), key.get(_E)
    if not isinstance(n, bytes) or not isinstance(e, bytes) or not n or not e:
        raise CoseError("malformed RSA key")
    modulus = int.from_bytes(n, "big")
    if modulus.bit_length() < 2048:        # un módulo que se puede factorizar es una firma que cualquiera falsifica
        raise CoseError("RSA modulus is too small")
    from cryptography.hazmat.primitives.asymmetric import rsa   # noqa: PLC0415
    return rsa.RSAPublicNumbers(int.from_bytes(e, "big"), modulus).public_key()


def verify(key: dict, alg: int, signature: bytes, data: bytes) -> bool:
    """Si ``signature`` firma ``data`` con esta clave. ``True`` o ``False``, nunca una excepción: todos los fallos
    (clave mal formada, firma mala, algoritmo distinto) deben ser indistinguibles para quien manda la aserción."""
    try:
        pub = public_key(key, alg)
        from cryptography.hazmat.primitives import hashes                    # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import ec, padding     # noqa: PLC0415
        if alg == ES256:
            pub.verify(bytes(signature), bytes(data), ec.ECDSA(hashes.SHA256()))
        elif alg == RS256:
            pub.verify(bytes(signature), bytes(data), padding.PKCS1v15(), hashes.SHA256())
        else:
            pub.verify(bytes(signature), bytes(data))                        # Ed25519 no lleva hash
        return True
    except Exception:  # noqa: BLE001
        return False

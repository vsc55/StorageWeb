"""Una ceremonia WebAuthn fabricada: una clave de verdad, unos datos de verdad y una firma de verdad.

No hay un vector publicado de una ceremonia entera (como los códigos que trae el RFC 6238), así que los tests la
construyen. Este es el constructor, y vive fuera de los ficheros de tests porque lo usan dos:
:mod:`tests.unit.test_mfa_webauthn`, que toma una ceremonia que SÍ verificaría y rompe una sola cosa cada vez, y
:mod:`tests.integration.test_passkeys`, que pasa una entera por HTTP para demostrar que las rutas la llevan.

Una copia en cada uno serían dos codificadores CBOR que pueden no estar de acuerdo en qué es una ceremonia válida, y el
día que discreparan uno de los dos estaría probando algo de sí mismo. Basado en el de ServiceSentry (mismo autor).

No se llama ``test_*`` a propósito: no tiene tests y no se debe recoger. El ``importorskip`` va al importar, así que
sin ``cryptography`` se saltan los ficheros que lo importan en vez de fallar al recogerlos.
"""

import hashlib
import json
import struct

import pytest

from storageweb.core.mfa import cose, webauthn as wa

pytest.importorskip('cryptography')

from cryptography.hazmat.primitives import hashes                    # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec             # noqa: E402

RP_ID = 'panel.example.com'
ORIGIN = 'https://panel.example.com'


def _cbor_map(pairs: dict) -> bytes:
    """Lo poquito de codificación CBOR que necesitan los tests (el decodificador es lo que se prueba)."""
    def item(v):
        if isinstance(v, int):
            if v >= 0:
                return bytes([0x00 | v]) if v < 24 else b'\x18' + bytes([v]) if v < 256 \
                    else b'\x19' + struct.pack('>H', v)
            n = -1 - v
            return bytes([0x20 | n]) if n < 24 else b'\x38' + bytes([n])
        if isinstance(v, bytes):
            return (bytes([0x40 | len(v)]) if len(v) < 24
                    else b'\x58' + bytes([len(v)])) + v
        raise TypeError(v)
    out = bytes([0xA0 | len(pairs)])
    for k, v in pairs.items():
        out += item(k) + item(v)
    return out


def _key():
    priv = ec.generate_private_key(ec.SECP256R1())
    n = priv.public_key().public_numbers()
    return priv, {1: cose.KTY_EC2, 3: cose.ES256, -1: cose.CRV_P256,
                  -2: n.x.to_bytes(32, 'big'), -3: n.y.to_bytes(32, 'big')}


def _auth_data(rp_id=RP_ID, flags=wa.FLAG_UP | wa.FLAG_AT, count=1,
               cred_id=b'cred-0001', cose_key=None, extra=b''):
    blob = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack('>I', count)
    if flags & wa.FLAG_AT:
        blob += b'\x00' * 16 + struct.pack('>H', len(cred_id)) + cred_id
        blob += _cbor_map(cose_key) if cose_key else b''
    return blob + extra


def _client_data(kind, challenge, origin=ORIGIN):
    return json.dumps({'type': kind, 'challenge': challenge, 'origin': origin,
                       'crossOrigin': False}).encode()


def _registration(challenge, origin=ORIGIN, **kw):
    priv, key = _key()
    auth = _auth_data(cose_key=key, **kw)
    att = b'\xa3' + b'\x63fmt' + b'\x64none' + b'\x67attStmt' + b'\xa0' \
          + b'\x68authData' + b'\x59' + struct.pack('>H', len(auth)) + auth
    return priv, key, att, _client_data('webauthn.create', challenge, origin)


def _assertion(priv, challenge, origin=ORIGIN, rp_id=RP_ID, flags=wa.FLAG_UP, count=2):
    auth = _auth_data(rp_id=rp_id, flags=flags, count=count)
    cdj = _client_data('webauthn.get', challenge, origin)
    sig = priv.sign(auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))
    return auth, cdj, sig

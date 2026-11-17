"""TOTP (RFC 6238) y el código QR (ISO/IEC 18004), contra los valores que publican las normas."""
import pytest

from storageweb.core.mfa import qr, totp

# RFC 6238, apéndice B: semilla ASCII «12345678901234567890», SHA-1, 8 dígitos
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.mark.parametrize("when, code", [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                                        (1234567890, "89005924"), (2000000000, "69279037"),
                                        (20000000000, "65353130")])
def test_rfc6238_vectors(when, code):
    assert totp.code_at(RFC_SECRET, totp.current_step(when), digits=8) == code
    assert totp.verify(RFC_SECRET, code, now=when, digits=8) == totp.current_step(when)


def test_window_and_replay():
    secret = totp.secret_new()
    now = 1_700_000_000
    step = totp.current_step(now)
    for offset in (-1, 0, 1):                       # medio minuto de reloj desviado, a cada lado
        assert totp.verify(secret, totp.code_at(secret, step + offset), now=now) == step + offset
    assert totp.verify(secret, totp.code_at(secret, step + 2), now=now) is None
    assert totp.verify(secret, totp.code_at(secret, step), now=now, after_step=step) is None   # ya usado
    assert totp.verify(secret, totp.code_at(secret, step - 1), now=now, after_step=step) is None


def test_bad_input_fails_closed():
    secret = totp.secret_new()
    assert totp.verify(secret, "", now=0) is None
    assert totp.verify(secret, "12345", now=0) is None
    assert totp.verify(secret, "١٢٣٤٥٦", now=0) is None      # dígitos de otra escritura
    assert totp.verify("no es base32!", "123456", now=0) is None
    assert totp.code_at("", 1) == ""
    code = totp.code_at(secret, totp.current_step(0))
    assert totp.verify(secret, f" {code[:3]} {code[3:]} ", now=0) is not None     # espacios: se toleran
    assert totp.secret_bytes(totp.secret_groups(secret).lower()) == totp.secret_bytes(secret)


def test_provisioning_uri():
    uri = totp.provisioning_uri("ABCD", "ana@ejemplo.com", "Storage Web")
    assert uri.startswith("otpauth://totp/Storage%20Web%3Aana%40ejemplo.com?")
    assert "secret=ABCD" in uri and "issuer=Storage+Web" in uri and "digits=6" in uri and "period=30" in uri
    assert len(totp.secret_new()) == 32 and totp.secret_groups("ABCDEFGH") == "ABCD EFGH"


def test_reed_solomon_against_a_published_example():
    # «HELLO WORLD», versión 1-M: los codewords de datos y los 10 de corrección que publica el ejemplo de la norma
    data = bytes([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17])
    assert list(qr.rs_ecc(data, 10)) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


def test_format_and_version_bits():
    # Tabla de la norma: nivel L con las máscaras 0 y 7, y la información de versión de la 7
    assert qr.format_bits(0) == 0b111011111000100
    assert qr.format_bits(4) == 0b110011000101111
    assert qr.format_bits(7) == 0b110100101110110
    assert qr.version_bits(7) == 0b000111110010010100


def test_symbol_structure_and_svg():
    uri = totp.provisioning_uri(totp.secret_new(), "ana.garcia", "StorageWeb")
    version = qr.best_version(len(uri.encode()))
    mod = qr.matrix(uri)
    assert len(mod) == version * 4 + 17
    for top, left in ((0, 0), (0, len(mod) - 7), (len(mod) - 7, 0)):   # los tres localizadores
        assert all(mod[top][left + c] for c in range(7)) and mod[top + 3][left + 3]
    assert all(mod[6][c] == (c % 2 == 0) for c in range(8, len(mod) - 8))   # sincronía
    out = qr.svg(uri)
    assert out.startswith("<svg") and "style" not in out and "ana.garcia" not in out   # sin estilos ni texto
    assert qr.svg("x" * 500) == "" and qr.best_version(500) == 0                       # no cabe: sin cuadrado

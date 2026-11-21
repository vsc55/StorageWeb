"""Lo justo de CBOR (RFC 8949) para leer lo que manda una passkey: el ``attestationObject`` y, dentro, la clave COSE.
Sin dependencias, como el QR de al lado, y comprobado contra la tabla de codificaciones del apéndice del RFC.
Basado en el de ServiceSentry (mismo autor).

**Solo decodifica**: el navegador manda CBOR y el servidor lo lee. Dos reglas que son de seguridad:

* **solo la forma canónica** (CTAP2 §6): sin longitudes indefinidas y cada argumento en la forma más corta que lo
  admite (``0x18 0x05`` no es un 5). Admitir otra serían dos codificaciones del mismo valor, y así se acaba firmando
  una y comprobando la otra. Del tipo 7 solo ``false``, ``true`` y ``null``: un float cuyos bits valgan 20 no es un
  ``false``.
* **el decodificador dice cuánto leyó.** Los datos del autenticador llevan la clave seguida de las extensiones, así
  que «lee el resto» no tiene respuesta: un lector que ignora lo que sobra no distingue una clave de una clave con
  algo pegado.
"""
from __future__ import annotations

import struct


class CborError(ValueError):
    """Mal formado, truncado o en una forma que no se admite. Una sola excepción: quien llama hace lo mismo con todos
    los casos (rechazar la ceremonia), y decir cuál fue sería dárselo a quien lo mandó."""


# Tope de cualquier elemento: una cabecera de dos bytes no puede pedir un gigabyte. Lo de WebAuthn son unos cientos
# de bytes; esto es mil veces más y aun así rechaza la longitud que dice 2^64
MAX_ITEM = 1 << 20
MAX_DEPTH = 16          # unos bytes de «[[[[…» no pueden llegar al límite de recursión en el inicio de sesión


def _head(data: bytes, i: int) -> tuple:
    """``(tipo mayor, argumento, índice siguiente)`` del elemento que empieza en ``i``."""
    if i >= len(data):
        raise CborError("truncated")
    initial = data[i]
    major, minor = initial >> 5, initial & 0x1F
    i += 1
    if minor < 24:
        return major, minor, i
    if major == 7:
        # 24 = valor simple en el byte siguiente (ninguno se usa aquí) y 25–27 son floats: lo que sigue no es un
        # argumento, y leerlo como tal convertiría unos bits en false, true o null
        raise CborError("unsupported simple value")
    if minor in (24, 25, 26, 27):
        width = {24: 1, 25: 2, 26: 4, 27: 8}[minor]
        if i + width > len(data):
            raise CborError("truncated")
        fmt = {1: ">B", 2: ">H", 4: ">I", 8: ">Q"}[width]
        value = struct.unpack(fmt, data[i:i + width])[0]
        # La forma más corta: lo que cabía en una anterior es otra codificación del mismo valor
        if value < (24 if width == 1 else 1 << (4 * width)):
            raise CborError("non-minimal encoding")
        return major, value, i + width
    # 28–30 reservados; 31 es la forma indefinida, que la codificación canónica de WebAuthn no usa
    raise CborError("indefinite or reserved length")


def _decode(data: bytes, i: int, depth: int) -> tuple:
    """``(valor, índice siguiente)``."""
    if depth > MAX_DEPTH:
        raise CborError("too deeply nested")
    major, arg, i = _head(data, i)
    if major == 0:                                   # entero sin signo
        return arg, i
    if major == 1:                                   # negativo: -1 - n
        return -1 - arg, i
    if major in (2, 3):                              # bytes / texto
        if arg > MAX_ITEM or i + arg > len(data):
            raise CborError("string too long or truncated")
        raw = data[i:i + arg]
        if major == 2:
            return raw, i + arg
        try:
            return raw.decode("utf-8"), i + arg
        except UnicodeDecodeError as exc:
            raise CborError("text is not utf-8") from exc
    if major == 4:                                   # lista
        if arg > MAX_ITEM:
            raise CborError("array too long")
        out = []
        for _ in range(arg):
            item, i = _decode(data, i, depth + 1)
            out.append(item)
        return out, i
    if major == 5:                                   # mapa
        if arg > MAX_ITEM:
            raise CborError("map too long")
        result = {}
        for _ in range(arg):
            key, i = _decode(data, i, depth + 1)
            if isinstance(key, (list, dict)):
                raise CborError("map key is not hashable")
            value, i = _decode(data, i, depth + 1)
            if key in result:        # dos claves iguales: elegir una sería elegir por quien lo mandó
                raise CborError("duplicate map key")
            result[key] = value
        return result, i
    if major == 6:                                   # etiqueta: lo que importa es el valor etiquetado
        return _decode(data, i, depth + 1)
    # tipo 7: valores simples
    if arg == 20:
        return False, i
    if arg == 21:
        return True, i
    if arg == 22:
        return None, i
    raise CborError("unsupported simple value")


def decode_from(data: bytes, offset: int = 0) -> tuple:
    """``(valor, bytes leídos)`` de UN elemento que empieza en ``offset``. El par es lo importante: la clave de la
    credencial va seguida de las extensiones y quien llama necesita saber dónde acabó."""
    value, end = _decode(bytes(data or b""), int(offset), 0)
    return value, end - int(offset)


def decode(data: bytes):
    """Un elemento que ocupa TODA la entrada: lo que sobra es un error (o es otra codificación de lo mismo o un
    segundo documento que nadie pidió)."""
    value, consumed = decode_from(data, 0)
    if consumed != len(bytes(data or b"")):
        raise CborError("trailing data")
    return value

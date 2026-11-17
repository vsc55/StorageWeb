"""Contraseñas de un solo uso basadas en el tiempo (RFC 6238), solo con la biblioteca estándar.

``hmac``, ``hashlib``, ``struct`` y ``base64`` son todo. Una dependencia aquí serían treinta líneas de
aritmética que no han cambiado desde 2011 (portado de ServiceSentry, del mismo autor).

**Puro:** ni Flask, ni base de datos, ni reloj propio salvo el que se pasa. Cada función depende solo de sus
argumentos, y por eso los vectores publicados en el propio RFC son un test y no un comentario. El estado vive
en :mod:`storageweb.core.mfa`.

Dos cosas fáciles de olvidar que son toda su seguridad:

* **se devuelve el paso, no un sí.** Un código vale treinta segundos, así que uno leído por encima del hombro
  (o en una página de phishing) funciona hasta que caduca. Quien llama guarda el paso que casó y rechaza ese y
  todos los anteriores: cada código vale exactamente una vez.
* **la comparación es ``hmac.compare_digest``.** Un ``==`` revelaría, por el tiempo que tarda, cuántos dígitos
  iniciales eran correctos, y seis dígitos adivinados de uno en uno no son seis dígitos.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

# Los valores que dan por hechos todas las aplicaciones de autenticación. Son parámetros de la URI porque la
# norma admite otros, pero en la práctica una aplicación que recibe otra cosa suele ignorarla: por eso no son
# ajustes, y aquí queda escrito por qué.
PERIOD = 30          # segundos por paso
DIGITS = 6           # longitud del código
ALGORITHM = "SHA1"   # el que implementan las aplicaciones; SHA256 está en la norma y casi nadie lo respeta
SECRET_BYTES = 20    # 160 bits: lo que pide el RFC 4226 y lo que llevan los enlaces otpauth:// reales
# Cuántos pasos a cada lado de ahora se aceptan. Uno = el reloj del móvil puede ir medio minuto desviado, algo
# lo bastante común como para que la tolerancia cero parezca «no funciona». Dos daría minuto y medio de validez
# al mismo código, que es el otro error.
WINDOW = 1


def secret_new(nbytes: int = SECRET_BYTES) -> str:
    """Una semilla nueva en base32, como la esperan las aplicaciones. De ``secrets``, nunca de ``random``."""
    return base64.b32encode(secrets.token_bytes(nbytes)).decode("ascii").rstrip("=")


def secret_bytes(secret: str) -> bytes:
    """Una semilla base32 como bytes, o ``b""`` si no lo es.

    Tolerante con lo que entra (minúsculas, espacios y los grupos de cuatro de la pantalla de alta), porque también
    lee lo que alguien tecleó a mano. Estricto con lo que sale: lo que no es base32 da vacío en vez de una
    excepción, y una semilla vacía no verifica nada.
    """
    text = "".join(str(secret or "").split()).upper()
    if not text:
        return b""
    text += "=" * (-len(text) % 8)   # base32 quiere múltiplos de ocho
    try:
        return base64.b32decode(text, casefold=True)
    except (ValueError, TypeError):
        return b""


def current_step(now: float | None = None, period: int = PERIOD) -> int:
    """En qué paso de tiempo cae ``now``: el contador que el RFC 6238 pasa a HOTP."""
    return int((time.time() if now is None else float(now)) // max(1, int(period)))


def code_at(secret: str, step: int, digits: int = DIGITS) -> str:
    """El código de un paso, con ceros a la izquierda: HOTP (RFC 4226) sobre el contador de pasos.

    Vacío si la semilla no es base32: quien lo compare con ``""`` falla cerrado, que es hacia donde tiene que fallar.
    """
    key = secret_bytes(secret)
    if not key:
        return ""
    mac = hmac.new(key, struct.pack(">Q", max(0, int(step))), hashlib.sha1).digest()
    # Truncado dinámico: el nibble bajo del último byte dice de dónde leer cuatro bytes, y se quita el bit alto para
    # que el resultado sea el mismo con cualquier idea de entero con signo.
    offset = mac[-1] & 0x0F
    trunc = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(trunc % (10 ** digits)).zfill(digits)


def verify(secret: str, code: str, *, now: float | None = None, period: int = PERIOD, digits: int = DIGITS,
           window: int = WINDOW, after_step: int = -1) -> int | None:
    """El paso con el que casó ``code``, o ``None``.

    El paso y no un booleano, porque un código ya usado no puede volver a valer: quien llama guarda lo que vuelve y lo
    pasa como ``after_step`` la siguiente vez.

    Se comprueban todos los pasos candidatos aunque uno ya haya casado: un bucle que sale antes tarda menos cuando el
    acierto está en el primer paso que en el último, y esa diferencia es un reloj que quien llama no controla (el
    mismo motivo por el que los dígitos se comparan con ``compare_digest``).
    """
    key = secret_bytes(secret)
    got = "".join(str(code or "").split())
    # También isascii(): isdigit() acepta dígitos de otras escrituras, y con texto no ASCII compare_digest lanza una
    # excepción en vez de contestar que no.
    if not key or not got.isascii() or not got.isdigit() or len(got) != int(digits):
        return None
    here = current_step(now, period)
    found = None
    for step in range(here - int(window), here + int(window) + 1):
        if step <= int(after_step):
            continue   # ya usado, o anterior a uno que lo fue (sin atajos: el bucle llega al final)
        if hmac.compare_digest(code_at(secret, step, digits), got) and found is None:
            found = step
    return found


def provisioning_uri(secret: str, account: str, issuer: str, digits: int = DIGITS, period: int = PERIOD) -> str:
    """El enlace ``otpauth://totp/…`` que una aplicación de autenticación lee del QR.

    El emisor aparece dos veces a propósito: en el prefijo de la etiqueta y como parámetro. El parámetro es el que
    define la norma; el prefijo, lo que leen las aplicaciones anteriores a ella. Todo va codificado, también los dos
    puntos, porque una cuenta es un email tan a menudo como no, y ``@`` y ``:`` en un segmento de ruta son la forma de
    que el enlace llegue cortado al móvil.
    """
    if not secret or not account:
        return ""
    label = urllib.parse.quote(f"{issuer}:{account}" if issuer else str(account), safe="")
    params = {"secret": str(secret), "algorithm": ALGORITHM, "digits": str(int(digits)), "period": str(int(period))}
    if issuer:
        params["issuer"] = str(issuer)
    return f"otpauth://totp/{label}?" + urllib.parse.urlencode(params)


def secret_groups(secret: str, size: int = 4) -> str:
    """La semilla en grupos de cuatro, como se lee de una pantalla y se teclea en un móvil."""
    text = str(secret or "")
    return " ".join(text[i:i + size] for i in range(0, len(text), size))

"""¿Aparece la contraseña en filtraciones conocidas? Pwned Passwords de Have I Been Pwned (``security.password_breach_check``).

**k-anonimato**: solo se envían los 5 primeros caracteres del SHA-1 de la contraseña; el servicio devuelve los
cientos de sufijos que empiezan así (con relleno, ``Add-Padding``, para que el tamaño de la respuesta tampoco diga
nada) y la comparación se hace aquí. Ni la contraseña ni su hash completo salen del servidor.

Si el servicio no contesta (sin salida a internet, caído), la contraseña **se acepta**: este control se suma a los
demás y no puede impedir que alguien ponga su contraseña. Solo biblioteca estándar.
"""
from __future__ import annotations

import hashlib
import logging
import urllib.error
import urllib.request

API = "https://api.pwnedpasswords.com/range/"
TIMEOUT = 5.0
log = logging.getLogger(__name__)


def _fetch(prefix: str, timeout: float) -> str:
    request = urllib.request.Request(API + prefix, headers={"Add-Padding": "true", "User-Agent": "StorageWeb"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 (URL fija, https)
        return resp.read(4 * 1024 * 1024).decode("ascii", errors="replace")


def times_breached(password: str, timeout: float = TIMEOUT) -> int | None:
    """Cuántas veces aparece en filtraciones (0 = ninguna) o None si no se pudo consultar."""
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324 (lo pide la API)
    prefix, suffix = digest[:5], digest[5:]
    try:
        body = _fetch(prefix, timeout)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        log.warning("Pwned Passwords no contesta (%s): la contraseña se acepta sin esa comprobación", exc)
        return None
    for line in body.splitlines():
        found, _sep, count = line.strip().partition(":")
        if found == suffix:
            try:
                return int(count)        # las de relleno llevan 0
            except ValueError:
                return None
    return 0

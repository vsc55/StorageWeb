"""Texto: comparar sin mayúsculas ni tildes, sacar de un nombre una clave legible, base64url, huellas SHA-256 y las
caducidades que se ofrecen. Sin dependencias ni Flask: lo usan ``core`` (buscar archivos, las claves de los roles,
los ``id`` de los encabezados de Markdown, enlaces y tokens), ``providers`` (OAuth/PKCE) y ``web``."""
from __future__ import annotations

import base64
import hashlib
import re
import unicodedata


def fold(text: str) -> str:
    """Sin mayúsculas ni tildes: «Informe Año» → «informe ano» (``casefold``: «Straße» → «strasse»)."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def slug(text: str, limit: int = 0) -> str:
    """Minúsculas sin tildes y guiones: «Diseño gráfico» → ``diseno-grafico``; ``limit`` corta (sin dejar un guion
    al final). Vacío si no queda nada."""
    plain = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return plain[:limit].rstrip("-") if limit else plain


def sha256_hex(text: str) -> str:
    """La huella SHA-256 de un texto (lo que se guarda de un token o de un enlace, nunca el secreto)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def b64url_encode(raw: bytes) -> str:
    """base64url sin relleno (JWT, PKCE, WebAuthn)."""
    return base64.urlsafe_b64encode(bytes(raw)).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    """base64url con o sin relleno a bytes; ``ValueError`` (``binascii.Error``) si no lo es."""
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_challenge(verifier: str) -> str:
    """El ``code_challenge`` S256 de un ``code_verifier`` (RFC 7636)."""
    return b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def offered_days(choices: tuple[int, ...], max_days: int = 0) -> list[int]:
    """Las caducidades que se ofrecen (días, de menor a mayor): con un máximo, las que no lo pasan y el propio
    máximo; sin máximo, todas y además «nunca» (0)."""
    if not max_days:
        return [*choices, 0]
    days = [d for d in choices if d <= max_days]
    return days if max_days in days else [*days, max_days]


def csv_names(value: str | None) -> set[str]:
    """Los nombres de un texto separado por comas, como se guardan los grupos de una cuenta (``"it,rrhh"``)."""
    return {x for x in (value or "").split(",") if x}


def clean_names(values) -> list[str]:
    """Nombres sin espacios alrededor, en minúsculas, sin repetir y ordenados (para guardarlos o compararlos)."""
    return sorted({str(v).strip().lower() for v in values or [] if str(v).strip()})


def initials(name: str) -> str:
    """Dos letras para un avatar: la primera de las dos primeras palabras («Recursos humanos» → «RH», «ana.garcia» →
    «AG») o, con una sola, sus dos primeras («Ventas» → «VE»)."""
    name = str(name or "").strip()
    parts = [p for p in re.split(r"[\s._-]+", name) if p]
    return ("".join(p[0] for p in parts[:2]) if len(parts) > 1 else name[:2]).upper()


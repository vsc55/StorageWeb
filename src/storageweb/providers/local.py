"""Contraseñas de usuarios locales (hash scrypt/pbkdf2 de Werkzeug)."""
from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

MIN_PASSWORD_LENGTH = 10

# Hash ficticio para igualar tiempos cuando el usuario no existe o no tiene contraseña
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")


def hash_password(password: str) -> str:
    validate_password(password)
    return generate_password_hash(password)


def verify(password_hash: str | None, password: str) -> bool:
    ok = check_password_hash(password_hash or _DUMMY_HASH, password)
    return ok and bool(password_hash)


def burn_time(password: str) -> None:
    """Consume el mismo tiempo que una verificación real."""
    check_password_hash(_DUMMY_HASH, password)

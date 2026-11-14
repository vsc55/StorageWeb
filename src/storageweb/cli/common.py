"""Piezas compartidas por los comandos (contraseñas, usuarios, errores)."""
from __future__ import annotations

import getpass
import sys

from ..db.repositories import users
from ..i18n import _
from ..providers import local


def _fail(message: str) -> None:
    sys.exit(message)


def _read_password(args) -> str | None:
    """Contraseña de --password, de --password-stdin o None (se preguntará)."""
    if getattr(args, "password_stdin", False):
        return sys.stdin.readline().rstrip("\r\n")
    return args.password


def _prompt_password() -> str:
    password = getpass.getpass(_("Password: "))
    if password != getpass.getpass(_("Repeat the password: ")):
        _fail(_("The passwords do not match."))
    return password


def _ask_password(given: str | None) -> str:
    try:
        return local.hash_password(given or _prompt_password())
    except ValueError as exc:
        _fail(str(exc))


def _groups(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _get(conn, username):
    user = users.get_by_username(conn, username)
    if user is None:
        _fail(_("The user %(name)s does not exist.", name=repr(username)))
    return user

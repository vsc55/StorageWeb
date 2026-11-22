"""Piezas compartidas por los comandos (registro, contraseñas, usuarios, errores).

Cada módulo declara sus comandos con :func:`command`: nombre, ayuda, sus argumentos y si necesita la
configuración y la base de datos. ``cli.build_parser`` los descubre; no hay una lista central.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from dataclasses import dataclass

from ..db.repositories import users
from ..i18n import _


@dataclass(frozen=True)
class Command:
    name: str
    help: object                                   # texto traducible (se traduce al construir el parser)
    run: Callable
    arguments: Callable[[argparse.ArgumentParser], None] | None = None
    needs_db: bool = True                          # True: run(cfg, conn, args); False: run(args) -> código
    order: int = 50


COMMANDS: dict[str, Command] = {}


def command(name: str, help, arguments: Callable[[argparse.ArgumentParser], None] | None = None, *,
            needs_db: bool = True, order: int = 50):
    """Registra un comando. ``arguments(parser)`` añade sus opciones (con los textos en ``_()``)."""
    def decorate(fn):
        COMMANDS.setdefault(name, Command(name, help, fn, arguments, needs_db, order))
        return fn
    return decorate
from ..providers import local


def _fail(message: str) -> None:
    sys.exit(message)


def config_error(exc) -> int:
    """Avisa de un error en la configuración y devuelve el código de salida (2) de todos los comandos."""
    print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
    return 2


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


def effective(cfg: dict, conn, args) -> dict:
    """Los ajustes efectivos: los de config.json y los guardados desde la web (la CLI solo lee el archivo). Si no se
    pueden leer los de la web, los del archivo. Se calculan una vez por orden (quedan en ``args``)."""
    cached = getattr(args, "_effective", None)
    if cached is not None:
        return cached
    try:
        from ..settings.runtime import open_runtime
        runtime, _boot = open_runtime(args.config, create_key=False)
        result = runtime.current(conn)
    except Exception:  # noqa: BLE001
        result = cfg
    args._effective = result
    return result


def password_rules(cfg: dict, conn, args) -> dict:
    """Las reglas de las contraseñas efectivas (``local.rules``)."""
    return local.rules(effective(cfg, conn, args))


def _groups(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _get(conn, username):
    user = users.get_by_username(conn, username)
    if user is None:
        _fail(_("The user %(name)s does not exist.", name=repr(username)))
    return user

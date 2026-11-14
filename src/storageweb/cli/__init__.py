"""Línea de comandos de StorageWeb: servidor y administración.

    storageweb serve [--dev] [--host H] [--port P]   arranca el servidor
    storageweb user-add admin --role admin           crea un usuario
    storageweb --help                                lista todos los comandos

En el servidor ejecútala con el usuario del servicio: ``sudo storageweb-admin <comando>``.
El idioma de los mensajes sale de STORAGEWEB_LANG, LC_ALL, LC_MESSAGES o LANG (es | en).

Un módulo por grupo de comandos (``server``, ``users``, ``config``, ``security``, ``backup``…). Cada
uno declara los suyos con ``common.command``: añadir un comando no toca este fichero.
"""
from __future__ import annotations

import argparse
import sys

from .. import i18n, registry
from ..db import connect, init_db
from ..i18n import _
from ..settings import ConfigError, load_config
from .common import COMMANDS, Command

def commands() -> list[Command]:
    registry.import_submodules(__name__)  # cada módulo registra sus comandos al importarse
    return sorted(COMMANDS.values(), key=lambda c: (c.order, c.name))


def build_parser() -> argparse.ArgumentParser:
    """Los textos de ayuda se traducen al construir el parser (idioma activo en ese momento)."""
    parser = argparse.ArgumentParser(prog="storageweb", description=_("StorageWeb: server and administration"))
    parser.add_argument("--config", metavar=_("PATH"),
                        help=_("Path to config.json (default $STORAGEWEB_CONFIG, then /etc/storageweb/config.json)"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in commands():
        p = sub.add_parser(cmd.name, help=str(cmd.help))
        if cmd.arguments:
            cmd.arguments(p)
    return parser


def main(argv: list[str] | None = None) -> int:
    token = i18n.set_locale(i18n.from_environment())
    try:
        return _main(argv)
    finally:
        i18n.reset_locale(token)


def _main(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    cmd = COMMANDS[args.cmd]
    if not cmd.needs_db:
        return cmd.run(args)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
        return 2
    init_db(cfg["database"])
    conn = connect(cfg["database"])
    try:
        cmd.run(cfg, conn, args)
    finally:
        conn.close()
    return 0

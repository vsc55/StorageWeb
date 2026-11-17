"""Notas de una versión: su sección del CHANGELOG.md, para la release de GitHub.

    python tools/release_notes.py 0.2.0            -> la sección «## [0.2.0] - …» por la salida estándar
    python tools/release_notes.py 0.2.0 --check    -> solo comprueba que existe y no está vacía

Termina con error si la versión no tiene sección: así un tag sin su entrada en el CHANGELOG
no llega a publicarse.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"


def notes(version: str, text: str) -> str | None:
    """El cuerpo de la sección ``## [version]`` (hasta la siguiente ``## [``), sin el título."""
    found = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.MULTILINE | re.DOTALL)
    if found is None:
        return None
    body = found.group(1).strip()
    return body or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help="versión sin la «v» (0.2.0, 1.3.0-rc1)")
    ap.add_argument("--check", action="store_true", help="solo comprobar que la sección existe")
    ap.add_argument("--changelog", type=Path, default=CHANGELOG)
    args = ap.parse_args(argv)
    body = notes(args.version, args.changelog.read_text(encoding="utf-8"))
    if body is None:
        print(f"CHANGELOG.md no tiene una sección «## [{args.version}]» con contenido: añádela antes de publicar.",
              file=sys.stderr)
        return 1
    if not args.check:
        sys.stdout.reconfigure(encoding="utf-8")
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())

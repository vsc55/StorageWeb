#!/usr/bin/env python3
"""Gestión de las traducciones (catálogos gettext de Babel).

    python tools/i18n.py update   # extrae los textos y actualiza messages.pot y los .po
    python tools/i18n.py check    # CI: catálogos al día, completos, sin "fuzzy" y con los mismos parámetros
    python tools/i18n.py stats    # cuántos textos hay y cuántos están traducidos

Flujo para traducir: ``update`` → editar ``src/storageweb/locale/<idioma>/LC_MESSAGES/messages.po``
(con un editor de texto, Poedit o Weblate) → ``check``. No hace falta compilar: la aplicación lee
los ``.po`` directamente.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "storageweb"
LOCALE_DIR = PKG / "locale"
POT = LOCALE_DIR / "messages.pot"
sys.path.insert(0, str(ROOT / "src"))

from storageweb.i18n import LOCALES, SOURCE_LOCALE  # noqa: E402

METHOD_MAP = [("**.py", "python"), ("web/templates/**.html", "jinja2")]
OPTIONS_MAP = {"web/templates/**.html": {"newstyle_gettext": "true"}}
KEYWORDS = {**DEFAULT_KEYWORDS, "_l": None, "lazy_gettext": None}
TARGETS = [loc for loc in LOCALES if loc != SOURCE_LOCALE]


def po_path(locale: str) -> Path:
    return LOCALE_DIR / locale / "LC_MESSAGES" / "messages.po"


def extract() -> Catalog:
    catalog = Catalog(project="StorageWeb", charset="utf-8", fuzzy=False)
    for filename, lineno, message, comments, context in extract_from_dir(
            str(PKG), METHOD_MAP, OPTIONS_MAP, keywords=KEYWORDS, comment_tags=("TRANSLATORS:",),
            strip_comment_tags=True):
        location = ("storageweb/" + filename.replace("\\", "/"), lineno)
        catalog.add(message, None, [location], auto_comments=comments, context=context)
    return catalog


def _write(path: Path, catalog: Catalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    # Sin números de línea: así el catálogo no cambia cada vez que se mueve código
    write_po(buf, catalog, width=100, omit_header=False, include_lineno=False, ignore_obsolete=True)
    path.write_bytes(buf.getvalue().replace(b"\r\n", b"\n"))


def read(locale: str) -> Catalog:
    with open(po_path(locale), "rb") as fh:
        return read_po(fh, locale=locale)


def update() -> None:
    template = extract()
    _write(POT, template)
    print(f"{POT.relative_to(ROOT).as_posix()}: {len(template)} textos")
    for locale in TARGETS:
        path = po_path(locale)
        catalog = read(locale) if path.exists() else Catalog(locale=locale, project="StorageWeb", fuzzy=False)
        catalog.update(template, no_fuzzy_matching=True, update_header_comment=False)
        _write(path, catalog)
        missing = sum(1 for m in catalog if m.id and not _translated(m))
        print(f"{path.relative_to(ROOT).as_posix()}: {len(catalog)} textos, {missing} sin traducir")


def _translated(message) -> bool:
    if isinstance(message.string, (list, tuple)):
        return all(message.string)
    return bool(message.string)


def check() -> list[str]:
    """Devuelve la lista de problemas (vacía si todo está bien)."""
    problems = []
    template_ids = {m.id for m in extract() if m.id}
    for locale in TARGETS:
        if not po_path(locale).exists():
            problems.append(f"{locale}: no existe {po_path(locale)}")
            continue
        catalog = read(locale)
        ids = {m.id for m in catalog if m.id}
        for msgid in sorted(map(str, template_ids - ids)):
            problems.append(f"{locale}: texto nuevo sin catálogo (ejecuta update): {msgid!r}")
        for msgid in sorted(map(str, ids - template_ids)):
            problems.append(f"{locale}: texto que ya no existe en el código (ejecuta update): {msgid!r}")
        for message in catalog:
            if not message.id:
                continue
            if message.fuzzy:
                problems.append(f"{locale}: traducción dudosa (fuzzy): {message.id!r}")
            elif not _translated(message):
                problems.append(f"{locale}: sin traducir: {message.id!r}")
        for message, errors in catalog.check():
            for error in errors:
                problems.append(f"{locale}: {message.id!r}: {error}")
    return problems


def stats() -> None:
    template = extract()
    print(f"Textos en el código: {len(template)}")
    for locale in TARGETS:
        catalog = read(locale)
        done = sum(1 for m in catalog if m.id and _translated(m) and not m.fuzzy)
        print(f"{locale}: {done}/{len(catalog)} traducidos")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("update", "check", "stats"))
    args = ap.parse_args(argv)
    if args.command == "update":
        update()
    elif args.command == "stats":
        stats()
    else:
        problems = check()
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print(f"\n{len(problems)} problemas en las traducciones", file=sys.stderr)
            return 1
        print("Traducciones correctas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

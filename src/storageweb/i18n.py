"""Internacionalización (gettext con Babel), independiente de Flask.

* Los textos fuente del código están en **inglés**; ``locale/<idioma>/LC_MESSAGES/messages.po``
  los traduce (de momento, ``es``).
* El idioma activo vive en una ``ContextVar``: la capa web lo fija en cada petición y la CLI a
  partir del entorno. Así ``core`` traduce sus mensajes sin depender de Flask.
* Los ``.po`` se compilan en memoria la primera vez que se usan (no hace falta versionar ``.mo``).
* Los mensajes de log no se traducen (se escriben en inglés).

Uso::

    from ..i18n import _, _l, ngettext
    raise AccountError(_("User %(name)s already exists", name=username))
    LABELS = {"admin": _l("Administrator")}          # se traduce al mostrarse
"""
from __future__ import annotations

import io
import os
from contextvars import ContextVar, Token
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from babel import Locale
from babel.dates import format_datetime as _babel_format_datetime
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from babel.numbers import format_decimal
from babel.support import LazyProxy, NullTranslations, Translations

SOURCE_LOCALE = "en"
LOCALES = ("en", "es")
DEFAULT_LOCALE = "en"
LOCALE_NAMES = {"en": "English", "es": "Español"}
LOCALE_DIR = Path(__file__).with_name("locale")
DOMAIN = "messages"

_current: ContextVar[str] = ContextVar("storageweb_locale", default=DEFAULT_LOCALE)


# --------------------------------------------------------------------------- catálogos

@lru_cache(maxsize=None)
def translations(locale: str) -> NullTranslations:
    """Catálogo de un idioma. El idioma fuente (inglés) no necesita catálogo."""
    po_file = LOCALE_DIR / locale / "LC_MESSAGES" / f"{DOMAIN}.po"
    if locale == SOURCE_LOCALE or not po_file.exists():
        return NullTranslations()
    with open(po_file, "rb") as fh:
        catalog = read_po(fh, locale=locale)
    buf = io.BytesIO()
    write_mo(buf, catalog)  # las entradas "fuzzy" se ignoran
    buf.seek(0)
    return Translations(buf, domain=DOMAIN)


# --------------------------------------------------------------------------- idioma activo

def normalize(tag: str | None) -> str | None:
    """'es-ES', 'es_ES.UTF-8', 'EN' -> 'es' / 'en'; None si no es un idioma disponible."""
    if not tag:
        return None
    primary = tag.replace("-", "_").split(".")[0].split("@")[0].split("_")[0].strip().lower()
    return primary if primary in LOCALES else None


def get_locale() -> str:
    return _current.get()


def set_locale(locale: str | None) -> Token:
    return _current.set(normalize(locale) or DEFAULT_LOCALE)


def reset_locale(token: Token) -> None:
    _current.reset(token)


def from_environment(default: str = DEFAULT_LOCALE) -> str:
    """Idioma para la CLI: STORAGEWEB_LANG, LC_ALL, LC_MESSAGES o LANG."""
    for var in ("STORAGEWEB_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        locale = normalize(os.environ.get(var))
        if locale:
            return locale
    return default


# --------------------------------------------------------------------------- traducción

def gettext(message: str, **params) -> str:
    text = translations(get_locale()).gettext(message)
    return text % params if params else text


def ngettext(singular: str, plural: str, num: int, **params) -> str:
    text = translations(get_locale()).ngettext(singular, plural, num)
    return text % {"num": num, **params}


def lazy_gettext(message: str, **params) -> LazyProxy:
    """Traducción diferida, para constantes de módulo (etiquetas, nombres de roles…)."""
    return LazyProxy(gettext, message, enable_cache=False, **params)


def raw_gettext(message: str) -> str:
    """Sin formatear: para Jinja (``newstyle``), que formatea y escapa los parámetros."""
    return translations(get_locale()).gettext(message)


def raw_ngettext(singular: str, plural: str, num: int) -> str:
    return translations(get_locale()).ngettext(singular, plural, num)


_ = gettext
_l = lazy_gettext


def N_(message: str) -> str:  # noqa: N802 (convención de gettext)
    """Marca un texto para extraerlo sin traducirlo todavía."""
    return message


# --------------------------------------------------------------------------- formatos

def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{format_decimal(size, format='#,##0.0', locale=get_locale())} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def format_datetime(value: datetime | str | None, fmt: str = "short") -> str:
    """Fecha y hora en el formato del idioma activo. Acepta ISO 8601 (como en la base de datos)."""
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return _babel_format_datetime(value, fmt, locale=get_locale())


def locale_display_name(locale: str) -> str:
    return LOCALE_NAMES.get(locale) or Locale.parse(locale).get_display_name(locale)

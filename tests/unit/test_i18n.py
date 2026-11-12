"""Internacionalización sin Flask: idioma activo, catálogos, plurales, formatos."""
import importlib.util
import re
from datetime import datetime
from pathlib import Path

import pytest

from storageweb import i18n
from storageweb.core.permissions import PERMISSION_LABELS, ROLE_LABELS

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "storageweb" / "web" / "templates"


@pytest.fixture
def locale():
    tokens = []

    def _set(code):
        tokens.append(i18n.set_locale(code))
    yield _set
    for token in reversed(tokens):
        i18n.reset_locale(token)


@pytest.mark.parametrize("tag, expected", [
    ("es", "es"), ("es-ES", "es"), ("es_MX.UTF-8", "es"), ("EN", "en"), ("en_US.utf8@euro", "en"),
    ("fr", None), ("C", None), ("C.UTF-8", None), ("", None), (None, None),
])
def test_normalize(tag, expected):
    assert i18n.normalize(tag) == expected


def test_from_environment(monkeypatch):
    for var in ("STORAGEWEB_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert i18n.from_environment() == i18n.DEFAULT_LOCALE
    monkeypatch.setenv("LANG", "C.UTF-8")
    assert i18n.from_environment() == i18n.DEFAULT_LOCALE
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.from_environment() == "en"
    monkeypatch.setenv("STORAGEWEB_LANG", "es")
    assert i18n.from_environment() == "es"


def test_unknown_locale_falls_back(locale):
    locale("fr")
    assert i18n.get_locale() == i18n.DEFAULT_LOCALE


def test_gettext_switches_language(locale):
    locale("en")
    assert i18n._("Wrong user name or password.") == "Wrong user name or password."
    locale("es")
    assert i18n._("Wrong user name or password.") == "Usuario o contraseña incorrectos."
    assert i18n._("Folder «%(name)s» created.", name="X") == "Carpeta «X» creada."


def test_untranslated_text_returns_source(locale):
    locale("es")
    assert i18n._("Text that is not in the catalog") == "Text that is not in the catalog"


def test_lazy_labels_follow_active_language(locale):
    locale("es")
    assert str(ROLE_LABELS["admin"]) == "Administrador"
    assert str(PERMISSION_LABELS["upload"]) == "Subir archivos"
    locale("en")
    assert str(ROLE_LABELS["admin"]) == "Administrator"
    assert str(PERMISSION_LABELS["upload"]) == "Upload files"


@pytest.mark.parametrize("num, es, en", [
    (1, "Subido 1 archivo.", "1 file uploaded."),
    (3, "Subidos 3 archivos.", "3 files uploaded."),
])
def test_plurals(locale, num, es, en):
    locale("es")
    assert i18n.ngettext("%(num)d file uploaded.", "%(num)d files uploaded.", num) == es
    locale("en")
    assert i18n.ngettext("%(num)d file uploaded.", "%(num)d files uploaded.", num) == en


def test_format_size(locale):
    locale("es")
    assert i18n.format_size(1536) == "1,5 KB"
    assert i18n.format_size(10) == "10 B"
    locale("en")
    assert i18n.format_size(1536) == "1.5 KB"
    assert i18n.format_size(3 * 1024 ** 3) == "3.0 GB"


def test_format_datetime(locale):
    moment = datetime(2026, 3, 1, 14, 5)
    locale("es")
    es = i18n.format_datetime(moment)
    locale("en")
    en = i18n.format_datetime(moment)
    assert es != en and "14:05" in es and "2:05" in en
    assert i18n.format_datetime(None) == "—"
    assert i18n.format_datetime("2026-03-01T14:05:00+00:00")
    assert i18n.format_datetime("no es una fecha") == "no es una fecha"


def test_core_errors_are_translated(locale):
    from storageweb.core.security import safe_filename

    locale("en")
    with pytest.raises(ValueError, match="Invalid file name"):
        safe_filename("..")
    locale("es")
    with pytest.raises(ValueError, match="Nombre de archivo no válido"):
        safe_filename("..")


# --------------------------------------------------------------------------- catálogos

_spec = importlib.util.spec_from_file_location("i18n_tool", ROOT / "tools" / "i18n.py")
i18n_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(i18n_tool)


def test_catalogs_complete_and_up_to_date():
    problems = i18n_tool.check()
    assert problems == [], "\n".join(problems[:20]) + "\n(ejecuta: python tools/i18n.py update)"


def test_js_messages_are_in_catalog(locale):
    from storageweb.web.js_messages import JS_MESSAGES, catalog

    locale("es")
    translated = catalog()
    assert set(translated) == set(JS_MESSAGES)
    assert translated["Are you sure?"] == "¿Seguro?"


_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
_SPANISH = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")


@pytest.mark.parametrize("template", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: p.name)
def test_templates_have_no_hardcoded_spanish(template):
    """El texto visible debe pasar por _(): fuera de las etiquetas Jinja no puede quedar español."""
    text = _JINJA.sub("", template.read_text(encoding="utf-8"))
    found = sorted({line.strip() for line in text.splitlines() if _SPANISH.search(line)})
    assert not found, found

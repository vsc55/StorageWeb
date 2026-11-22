"""Notas de la release sacadas del CHANGELOG (tools/release_notes.py)."""
from tests.helpers import ROOT, load_tool

release_notes = load_tool("tools/release_notes.py")

SAMPLE = """# Registro de cambios

## [Sin publicar]

## [0.2.0] - 2026-12-01

### Añadido

- Algo nuevo.

## [0.1.0] - 2026-11-16

- Lo primero.
"""


def test_section_of_a_version_without_the_next_one():
    assert release_notes.notes("0.2.0", SAMPLE) == "### Añadido\n\n- Algo nuevo."
    assert release_notes.notes("0.1.0", SAMPLE) == "- Lo primero."


def test_missing_or_empty_section():
    assert release_notes.notes("0.3.0", SAMPLE) is None
    assert release_notes.notes("Sin publicar", SAMPLE) is None      # vacía
    assert release_notes.notes("0.1", SAMPLE) is None              # no vale un prefijo


def test_cli_fails_without_section(tmp_path, capsys):
    log = tmp_path / "CHANGELOG.md"
    log.write_text(SAMPLE, encoding="utf-8")
    assert release_notes.main(["0.2.0", "--changelog", str(log)]) == 0
    assert "Algo nuevo" in capsys.readouterr().out
    assert release_notes.main(["9.9.9", "--check", "--changelog", str(log)]) == 1


def test_published_versions_have_notes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Primera versión publicada" in release_notes.notes("0.1.0", text)

"""Notas de la release sacadas del CHANGELOG (tools/release_notes.py)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("release_notes", ROOT / "tools" / "release_notes.py")
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)

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

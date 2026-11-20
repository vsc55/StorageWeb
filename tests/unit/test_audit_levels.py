"""Niveles de la auditoría (storageweb/audit_levels.py) y que la referencia diga los mismos que el código."""
from __future__ import annotations

import re
from pathlib import Path

from storageweb import audit_levels as al

DOC = Path(__file__).resolve().parents[2] / "docs" / "referencia" / "auditoria.md"


def test_levels_by_action():
    assert al.level_of("folder_listed") == "debug"
    assert al.level_of("download") == "info" and al.level_of("download", "view") == "debug"
    assert al.level_of("upload") == "info"
    assert al.level_of("login_failed") == "warning" and al.level_of("quota_exceeded") == "warning"
    assert al.level_of("backup_failed") == "error"
    assert al.level_of("login_blocked") == "critical" and al.level_of("audit_purged") == "critical"
    assert al.level_of("location_tested", "ok") == "info" and al.level_of("location_tested", "timeout") == "warning"
    assert al.level_of("una_accion_nueva") == "info"


def test_minimum_and_ranges():
    assert al.levels_from("warning") == ("warning", "error", "critical")
    assert al.at_least("error", "warning") and not al.at_least("info", "warning")
    try:
        al.configure("warning")
        assert not al.recorded("info") and al.recorded("critical")
        al.configure("nada")
        assert al.recorded("debug")                      # un valor raro: todo
    finally:
        al.configure("debug")


def test_reference_says_the_same_level():
    """La columna «Nivel» de docs/referencia/auditoria.md coincide con level_of (salvo las de dos niveles)."""
    rows = re.findall(r"^\| `([a-z_]+)` \| `([a-z]+)` \|", DOC.read_text(encoding="utf-8"), re.M)
    assert len(rows) > 80
    wrong = [(action, level, al.level_of(action)) for action, level in rows if al.level_of(action) != level]
    assert wrong == []

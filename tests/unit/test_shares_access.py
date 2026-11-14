"""Acceso por carpeta: read_only_users, entradas «quién entra» y avisos del Resumen."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from storageweb.core import alerts
from storageweb.core import shares as sc
from storageweb.core.storage import share_access


def _share(**kw):
    base = {"name": "s", "label": "S", "path": "/x", "read_only": False, "users": [], "read_only_users": [],
            "groups": [], "read_only_groups": []}
    return {**base, **kw}


@pytest.mark.parametrize("share, uname, groups, expected", [
    (_share(users=["ana"]), "ana", set(), "write"),
    (_share(users=["ana"], read_only_users=["ana"]), "ana", set(), "read"),
    (_share(users=["*"], read_only_users=["*"]), "ana", set(), "read"),
    (_share(users=["*"]), "ana", set(), "write"),
    # Basta con una vía con escritura
    (_share(users=["ana"], read_only_users=["ana"], groups=["it"]), "ana", {"it"}, "write"),
    (_share(users=["*"], read_only_users=["*"], groups=["it"], read_only_groups=["it"]), "ana", {"it"}, "read"),
    (_share(groups=["it", "fin"], read_only_groups=["it"]), "ana", {"it", "fin"}, "write"),
    # La carpeta de solo lectura manda
    (_share(users=["ana"], read_only=True), "ana", set(), "read"),
    (_share(users=["eva"], groups=["it"]), "ana", {"fin"}, "none"),
])
def test_share_access(share, uname, groups, expected):
    assert share_access(share, uname, groups) == expected


def test_entries_roundtrip():
    share = _share(users=["*", "ana"], read_only_users=["ana"], groups=["it", "fin"], read_only_groups=["fin"])
    items = sc.entries(share)
    assert items == [{"kind": "all", "ref": "*", "level": "write"}, {"kind": "user", "ref": "ana", "level": "read"},
                     {"kind": "group", "ref": "it", "level": "write"}, {"kind": "group", "ref": "fin", "level": "read"}]
    assert sc.with_entries(_share(), items) == share


def test_with_entries_normalizes_and_deduplicates():
    result = sc.with_entries(_share(), [{"kind": "user", "ref": " Ana ", "level": "read"},
                                        {"kind": "user", "ref": "ana", "level": "write"},
                                        {"kind": "user", "ref": "*", "level": "read"},
                                        {"kind": "group", "ref": "", "level": "write"}])
    assert result["users"] == ["ana", "*"] and result["read_only_users"] == ["ana", "*"] and result["groups"] == []
    with pytest.raises(sc.ShareError):
        sc.with_entries(_share(), [{"kind": "robot", "ref": "x", "level": "write"}])


def test_replace_and_remove():
    shares = [_share(name="a"), _share(name="b")]
    assert [s["name"] for s in sc.replace(shares, "a", _share(name="c"))] == ["c", "b"]
    assert [s["name"] for s in sc.replace(shares, None, _share(name="d"))] == ["a", "b", "d"]
    with pytest.raises(sc.ShareError):
        sc.replace(shares, None, _share(name="a"))
    assert [s["name"] for s in sc.remove(shares, "a")] == ["b"]
    assert shares[0]["name"] == "a"  # no se modifica la lista original


def _cfg(tmp_path, **entra):
    return {"auth": {"entra": {"client_id": "", "secret_expires": "", **entra}},
            "storage": {"create_shares": False, "shares": [_share(name="sw", label="Software", path=str(tmp_path / "no"))]},
            "maintenance": {"backup_interval_hours": 0}}


def test_alerts(tmp_path):
    soon = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).isoformat(timespec="seconds")
    found = alerts.collect(_cfg(tmp_path, client_id="app", secret_expires=soon), {"data_dir": str(tmp_path)}, {})
    assert [a["key"] for a in found] == ["secret_expiring", "share_missing"]
    assert found[0]["level"] == "danger" and found[0]["page"] == "auth" and "5" in found[0]["title"]
    assert found[1]["page"] == "folders" and found[1]["anchor"] == "share-sw"
    (tmp_path / "no").mkdir()
    assert alerts.collect(_cfg(tmp_path), {"data_dir": str(tmp_path)}, {}) == []


def test_backup_alert_only_after_a_try(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "no").mkdir()
    cfg["maintenance"]["backup_interval_hours"] = 24
    boot = {"data_dir": str(tmp_path), "database": str(tmp_path / "db.sqlite")}
    assert alerts.collect(cfg, boot, {}) == []                     # recién instalado: aún no tocaba
    found = alerts.collect(cfg, boot, {"backup": "2026-01-01T00:00:00+00:00"})
    assert [a["key"] for a in found] == ["backup_stale"] and found[0]["page"] == "backups"

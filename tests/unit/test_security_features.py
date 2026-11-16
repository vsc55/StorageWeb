"""Bloqueo de IPs, tokens de API, mantenimiento y marca (núcleo, sin Flask)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from storageweb.core import branding, ipban, maintenance, tokens
from storageweb.db.repositories import api_tokens, audit, ip_rules, sessions, users
from storageweb.settings import load_config


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"data_dir": str(tmp_path / "data"),
                             "security": {"ipban_threshold": 3, "ipban_window_minutes": 10, "ipban_minutes": 60}}),
                 encoding="utf-8")
    return load_config(p)


@pytest.fixture(autouse=True)
def fresh_cache():
    ipban.invalidate()
    yield
    ipban.invalidate()


# --------------------------------------------------------------------------- IPs

@pytest.mark.parametrize("text, expected", [("203.0.113.7", "203.0.113.7"), ("10.1.2.3/8", "10.0.0.0/8"),
                                            ("2001:db8::1", "2001:db8::1"), (" 192.168.1.0/24 ", "192.168.1.0/24")])
def test_normalize_network(text, expected):
    assert ipban.normalize_network(text) == expected


def test_normalize_network_invalid():
    with pytest.raises(ipban.IPBanError):
        ipban.normalize_network("no-es-ip")


def test_automatic_ban_after_threshold(db_conn, cfg):
    ip = "203.0.113.7"
    assert not ipban.offense(db_conn, cfg, ip, "login_failed")
    assert not ipban.offense(db_conn, cfg, ip, "csrf")
    assert ipban.offense(db_conn, cfg, ip, "login_failed")         # tercera: bloqueada
    rule = ipban.banned(db_conn, ip)
    assert rule and rule["automatic"] and rule["expires_at"]
    assert ipban.banned(db_conn, "203.0.113.8") is None
    assert [r["action"] for r in audit.recent(db_conn, 5)] == ["ip_banned"]


def test_loopback_allowlist_and_disabled_never_banned(db_conn, cfg):
    for _ in range(5):
        ipban.offense(db_conn, cfg, "127.0.0.1", "login_failed")
    assert ipban.banned(db_conn, "127.0.0.1") is None
    ipban.allow(db_conn, "198.51.100.0/24", by="root")
    for _ in range(5):
        ipban.offense(db_conn, cfg, "198.51.100.20", "login_failed")
    assert ipban.banned(db_conn, "198.51.100.20") is None
    off = {**cfg, "security": {**cfg["security"], "ipban_enabled": False}}
    for _ in range(5):
        ipban.offense(db_conn, off, "192.0.2.1", "login_failed")
    assert ipban.banned(db_conn, "192.0.2.1") is None


def test_manual_ban_network_and_self_protection(db_conn):
    with pytest.raises(ipban.IPBanError, match="usando"):
        ipban.ban(db_conn, "192.0.2.0/24", by="root", current_ip="192.0.2.50")
    net = ipban.ban(db_conn, "192.0.2.0/24", by="root", reason="pruebas", current_ip="198.51.100.1")
    assert ipban.banned(db_conn, "192.0.2.77")["network"] == net
    ipban.allow(db_conn, "192.0.2.77", by="root")
    assert ipban.banned(db_conn, "192.0.2.77") is None            # la lista blanca gana


def test_expired_ban_ignored_and_pruned(db_conn, cfg):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
    ip_rules.add(db_conn, "ban", "203.0.113.9", expires_at=past)
    ipban.invalidate()
    assert ipban.banned(db_conn, "203.0.113.9") is None
    ipban.prune(db_conn, cfg)
    assert ip_rules.list_rules(db_conn) == []


# --------------------------------------------------------------------------- tokens

def _user(conn, name="ana", **kw):
    return users.get_by_id(conn, users.create(conn, username=name, source="local", **kw))


def test_token_lifecycle(db_conn):
    user = _user(db_conn)
    plain, tid = tokens.create(db_conn, user, name="script", scope="read", days=30)
    assert plain.startswith("sw_") and api_tokens.get(db_conn, tid)["token_hash"] != plain
    found_user, token = tokens.authenticate(db_conn, plain, "192.0.2.1")
    assert found_user["id"] == user["id"] and token["scope"] == "read"
    assert api_tokens.get(db_conn, tid)["last_ip"] == "192.0.2.1"
    assert tokens.authenticate(db_conn, plain + "x") is None
    assert tokens.authenticate(db_conn, "otro") is None
    users.update(db_conn, user["id"], enabled=False)
    assert tokens.authenticate(db_conn, plain) is None


def test_token_expired_and_validation(db_conn):
    user = _user(db_conn)
    plain, tid = tokens.create(db_conn, user, name="viejo", scope="write", days=0)
    assert api_tokens.get(db_conn, tid)["expires_at"] is None
    db_conn.execute("UPDATE api_tokens SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (tid,))
    assert tokens.authenticate(db_conn, plain) is None
    for kwargs in ({"name": "", "scope": "read", "days": 30}, {"name": "x", "scope": "admin", "days": 30},
                   {"name": "x", "scope": "read", "days": 7}):
        with pytest.raises(tokens.TokenError):
            tokens.create(db_conn, user, **kwargs)


def test_token_scope_restricts_permissions():
    perms = frozenset({"upload", "download", "mkdir"})
    assert tokens.restrict(perms, None) == perms
    assert tokens.restrict(perms, {"scope": "write"}) == perms
    assert tokens.restrict(perms, {"scope": "read"}) == {"download"}


# --------------------------------------------------------------------------- mantenimiento

def test_purge_and_vacuum(db_conn, tmp_path):
    db_conn.execute("INSERT INTO audit_log (ts, action) VALUES ('2000-01-01T00:00:00+00:00', 'viejo')")
    audit.log(db_conn, "nuevo")
    assert maintenance.purge_audit(db_conn, 0) == 0
    assert maintenance.purge_audit(db_conn, 30) == 1
    assert [r["action"] for r in audit.recent(db_conn, 5)] == ["nuevo"]
    database = db_conn.execute("PRAGMA database_list").fetchone()["file"]
    before, after = maintenance.vacuum(db_conn, database)
    assert before > 0 and after > 0
    stats = maintenance.db_stats(db_conn, database)
    assert stats["tables"]["audit_log"] == 1 and stats["size"] > 0


def test_run_due_cleans_and_backs_up(db_conn, tmp_path):
    database = db_conn.execute("PRAGMA database_list").fetchone()["file"]
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"data_dir": str(tmp_path / "d"), "database": database,
                             "maintenance": {"audit_retention_days": 10, "backup_interval_hours": 1, "backup_keep": 2}}),
                 encoding="utf-8")
    cfg = load_config(p)
    user = _user(db_conn)
    sessions.create(db_conn, "viejo", user["id"], None, None)
    db_conn.execute("UPDATE sessions SET last_seen = '2000-01-01T00:00:00+00:00'")
    db_conn.execute("INSERT INTO audit_log (ts, action) VALUES ('2000-01-01T00:00:00+00:00', 'viejo')")
    db_conn.commit()
    done = maintenance.run_due(db_conn, cfg)
    assert done == ["cleanup", "ipban_prune", "audit_purge", "backup"]
    assert sessions.get(db_conn, "viejo") is None and len(maintenance.list_backups(cfg)) == 1
    assert maintenance.run_due(db_conn, cfg) == []                    # nada pendiente hasta la próxima
    name = maintenance.list_backups(cfg)[0]["name"]
    assert maintenance.backup_path(cfg, name) is not None
    for bad in ("../x", "/etc/passwd", ".hidden", "no-existe.tar.gz"):
        assert maintenance.backup_path(cfg, bad) is None


# --------------------------------------------------------------------------- marca

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff" + b"\0" * 64


def test_logo_save_validate_and_replace(cfg):
    assert branding.save_image(cfg, "logo", "Logo.PNG", PNG) == "logo.png"
    assert branding.save_image(cfg, "logo", "x.svg", b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>") == "logo.svg"
    assert sorted(p.name for p in branding.brand_dir(cfg).iterdir()) == ["logo.svg"]
    for name, data in (("x.gif", PNG), ("x.png", b"no-png"), ("x.png", b""), ("x.png", PNG * 10000)):
        with pytest.raises(branding.BrandingError):
            branding.save_image(cfg, "logo", name, data)
    branding.remove_image(cfg, "logo")
    assert list(branding.brand_dir(cfg).iterdir()) == []


def test_login_image_is_separate_from_the_logo_and_allows_more(cfg):
    big = PNG * 10000                                                        # ~720 KB: demasiado para el logo
    assert branding.save_image(cfg, "logo", "l.png", PNG) == "logo.png"
    assert branding.save_image(cfg, "login_image", "Foto.JPEG", JPEG) == "login.jpg"
    assert branding.save_image(cfg, "login_image", "f.png", big) == "login.png"   # sustituye a login.jpg
    assert sorted(p.name for p in branding.brand_dir(cfg).iterdir()) == ["login.png", "logo.png"]
    with pytest.raises(branding.BrandingError):
        branding.save_image(cfg, "login_image", "f.png", PNG * 50000)          # más de 3 MB
    branding.remove_image(cfg, "login_image")
    assert sorted(p.name for p in branding.brand_dir(cfg).iterdir()) == ["logo.png"]


def test_stylesheet_and_color_validation(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"branding": {"primary_color": "#AA3300"}}), encoding="utf-8")
    css = branding.stylesheet(load_config(p))
    assert "--primary: #aa3300" in css and "color-mix" in css
    p.write_text(json.dumps({"branding": {"primary_color": "rojo"}}), encoding="utf-8")
    from storageweb.settings import ConfigError
    with pytest.raises(ConfigError):
        load_config(p)


def test_token_rotation_keeps_expiry_policy(db_conn):
    from storageweb.core import tokens
    from storageweb.db.repositories import api_tokens
    from storageweb.db.repositories import users as users_repo
    users_repo.create(db_conn, username="ana", source="local")
    user = db_conn.execute("SELECT * FROM users WHERE username = 'ana'").fetchone()
    for days in (30, 90, 365, 0):
        _plain, tid = tokens.create(db_conn, user, name=f"t{days}", scope="write", days=days)
        assert tokens.original_days(api_tokens.get(db_conn, tid)) == days
        _new, new_id = tokens.rotate(db_conn, user, api_tokens.get(db_conn, tid))
        assert api_tokens.get(db_conn, tid) is None
        rotated = api_tokens.get(db_conn, new_id)
        assert tokens.original_days(rotated) == days and rotated["name"] == f"t{days}"

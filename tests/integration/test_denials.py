"""Cuando se deniega algo a mitad de uso: el motivo para los programas (cabecera X-StorageWeb-Reason), la sesión que
se cierra con la página abierta, las descargas largas que se cortan y las subidas por partes que quedan a medias."""
from __future__ import annotations

import pytest

from storageweb.core import accounts, groups as gc, maintenance
from storageweb.core import uploads as uploads_core
from storageweb.db.repositories import uploads as uploads_repo, users
from storageweb.web import downloads
from storageweb.web.context import get_db
from tests.helpers import PASSWORD, add_user, api_token, basic_auth, last_audit, signed_in, update_settings

REASON = "X-StorageWeb-Reason"
BIG = 200_000        # varios trozos de envío


@pytest.fixture
def app(make_app, tmp_path):
    shared = tmp_path / "equipo"
    shared.mkdir()
    (shared / "grande.bin").write_bytes(b"x" * BIG)
    return make_app({"storage": {"create_shares": True, "max_file_size_mb": 1, "shares": [
        {"name": "equipo", "label": "Equipo", "path": str(shared), "users": [], "groups": ["it"]},
        {"name": "lectura", "path": str(tmp_path / "ro"), "users": ["*"], "read_only": True}]}})


def _disable(app, username):
    with app.app_context():
        accounts.set_enabled(get_db(), users.get_by_username(get_db(), username), None, False)


def _dav(client, secret, method="PROPFIND", path="/dav/", user="ana", **kw):
    return client.open(path, method=method, headers={**basic_auth(user, secret), "Depth": "1"}, **kw)


# --------------------------------------------------------------------------- el motivo

def test_tokens_say_why(app):
    add_user(app, "ana")
    client = app.test_client()
    plain = api_token(app)
    assert _dav(client, plain).status_code == 207
    bad = _dav(client, "sw_inventado")
    assert bad.status_code == 401 and bad.headers[REASON] == "token_invalid"
    with app.app_context():
        get_db().execute("UPDATE api_tokens SET expires_at = '2000-01-01T00:00:00+00:00'")
        get_db().commit()
    expired = _dav(client, plain)
    assert expired.status_code == 401 and expired.headers[REASON] == "token_expired"
    assert last_audit(app, "login_failed")["detail"] == "webdav:token_expired"
    # La API con Bearer, igual
    other = api_token(app, name="otro")
    _disable(app, "ana")
    resp = client.get("/api/uploads/x", headers={"Authorization": f"Bearer {other}"})
    assert resp.status_code == 401 and resp.headers[REASON] == "account_disabled"
    assert _dav(client, other).headers[REASON] == "account_disabled"
    update_settings(app, security={"api_tokens": False})
    assert _dav(client, other).headers[REASON] == "tokens_disabled"


def test_expired_or_disabled_tokens_are_not_offenses(app, monkeypatch):
    """Un programa con un token que fue bueno reintenta solo: no cuenta para bloquear la IP de la oficina (uno
    inventado, sí)."""
    from storageweb.core import ipban
    offenses = []
    monkeypatch.setattr(ipban, "offense", lambda conn, cfg, ip, kind: offenses.append(kind))
    add_user(app, "ana")
    client = app.test_client()
    plain = api_token(app)
    _disable(app, "ana")
    for _ in range(3):
        assert _dav(client, plain).headers[REASON] == "account_disabled"
        client.get("/api/uploads/x", headers={"Authorization": f"Bearer {plain}"})
    assert offenses == []
    client.get("/api/uploads/x", headers={"Authorization": "Bearer sw_inventado"})
    assert offenses == ["bad_token"]


def test_passwords_say_why(app):
    add_user(app, "ana")
    client = app.test_client()
    resp = _dav(client, PASSWORD)
    assert resp.status_code == 401 and resp.headers[REASON] == "password_not_allowed"
    update_settings(app, security={"webdav_passwords": True})
    assert _dav(client, PASSWORD).status_code == 207
    _disable(app, "ana")
    assert _dav(client, PASSWORD).headers[REASON] == "account_disabled"     # contraseña buena, cuenta desactivada
    assert REASON not in _dav(client, "mala").headers                       # una mala no revela nada


def test_writes_say_why(app, tmp_path):
    add_user(app, "ana")
    client = app.test_client()
    with app.app_context():
        gc.add_member(get_db(), gc.repo.get_by_id(get_db(), gc.create_group(get_db(), name="it")),
                      users.get_by_username(get_db(), "ana"))
    write, read = api_token(app), api_token(app, scope="read", name="lectura")
    assert _dav(client, write, "PUT", "/dav/lectura/a.txt", data=b"x").headers[REASON] == "read_only"
    assert _dav(client, read, "PUT", "/dav/equipo/a.txt", data=b"x").headers[REASON] == "token_read_only"
    assert _dav(client, write, "PUT", "/dav/equipo/a.txt", data=b"x").status_code == 201
    big = _dav(client, write, "PUT", "/dav/equipo/b.bin", data=b"x" * (2 * 1024 * 1024))
    assert big.status_code == 413 and big.headers[REASON] == "too_large"
    update_settings(app, permissions={"user": {"upload": False}})
    assert _dav(client, write, "PUT", "/dav/equipo/c.txt", data=b"x").headers[REASON] == "no_permission"


def test_banned_ip_and_maintenance(app, monkeypatch):
    from storageweb.core import ipban
    add_user(app, "ana")
    client = app.test_client()
    with monkeypatch.context() as m:
        m.setattr(ipban, "banned", lambda conn, ip: {"network": ip})
        resp = client.get("/login")
        assert resp.status_code == 403 and resp.headers[REASON] == "ip_banned"
    maintenance.RESTORING.set()
    try:
        resp = _dav(client, api_token(app))
        assert resp.status_code == 503 and resp.headers[REASON] == "maintenance"
    finally:
        maintenance.RESTORING.clear()


def test_the_page_javascript_learns_the_session_ended(app):
    client, token = signed_in(app)
    with app.app_context():
        get_db().execute("DELETE FROM sessions")                            # la cierra un admin (o se desactiva)
        get_db().commit()
    for headers in ({"Accept": "application/json"}, {"X-CSRF-Token": token}, {"X-Requested-With": "fetch"}):
        resp = client.get("/recent", headers=headers)
        assert resp.status_code == 401 and resp.headers[REASON] == "signed_out", headers
        assert resp.get_json()["login"] == "/login" and "sesión" in resp.get_json()["error"]
    assert client.get("/recent").status_code == 302                        # una página: a la entrada, como siempre


# --------------------------------------------------------------------------- descargas que se cortan

@pytest.fixture
def check_always(monkeypatch):
    monkeypatch.setattr(downloads, "CHECK_SECONDS", 0)


def _start(resp):
    """El primer trozo de una respuesta sin leer el resto todavía."""
    body = iter(resp.response)
    return body, len(next(body))


def _rest(body) -> int:
    return sum(len(chunk) for chunk in body)


def test_a_download_stops_when_the_account_is_disabled(app, home, check_always):
    home.mkdir(parents=True)
    (home / "grande.bin").write_bytes(b"y" * BIG)
    client, _token = signed_in(app)
    resp = client.get("/download/home/grande.bin", buffered=False)
    assert resp.status_code == 200 and resp.content_length == BIG
    body, first = _start(resp)
    _disable(app, "ana")
    assert first + _rest(body) < BIG                                       # cortada: el cliente sabe que le falta
    assert last_audit(app, "download_cut")["detail"] == "account_disabled"
    # Sin cambios, entera
    client2, _t = signed_in(app, "luis")
    (home.parent / "luis").mkdir(parents=True, exist_ok=True)
    (home.parent / "luis" / "f.bin").write_bytes(b"z" * BIG)
    whole = client2.get("/download/home/f.bin", buffered=False)
    body, first = _start(whole)
    assert first + _rest(body) == BIG


def test_a_webdav_download_stops_when_the_group_is_disabled(app, check_always):
    add_user(app, "ana")
    with app.app_context():
        gid = gc.create_group(get_db(), name="it")
        gc.add_member(get_db(), gc.repo.get_by_id(get_db(), gid), users.get_by_username(get_db(), "ana"))
    client = app.test_client()
    resp = _dav(client, api_token(app), "GET", "/dav/equipo/grande.bin", buffered=False)
    assert resp.status_code == 200
    body, first = _start(resp)
    with app.app_context():
        gc.set_enabled(get_db(), gc.repo.get_by_id(get_db(), gid), False)
    assert first + _rest(body) < BIG
    assert last_audit(app, "download_cut")["detail"].startswith("no_access")


def test_a_zip_stops_when_the_session_is_closed(app, home, check_always):
    (home / "carpeta").mkdir(parents=True)
    for i in range(20):
        (home / "carpeta" / f"f{i}.bin").write_bytes(bytes(range(256)) * 400)
    client, _token = signed_in(app)
    resp = client.get("/zip/home/carpeta", buffered=False)
    assert resp.status_code == 200
    body, _first = _start(resp)
    with app.app_context():
        get_db().execute("DELETE FROM sessions")
        get_db().commit()
    _rest(body)
    assert last_audit(app, "download_cut")["detail"].startswith("signed_out")


def test_a_share_link_download_stops_when_revoked(app, home, check_always):
    update_settings(app, permissions={"user": {"share": True}})
    home.mkdir(parents=True)
    (home / "grande.bin").write_bytes(b"y" * BIG)
    owner, csrf = signed_in(app)
    data = owner.post("/links", data={"root": "home", "path": "grande.bin"},
                      headers={"X-CSRF-Token": csrf, "Accept": "application/json"}).get_json()
    plain = data["url"].rsplit("/s/", 1)[1]
    resp = app.test_client().get(f"/s/{plain}/download", buffered=False)
    assert resp.status_code == 200
    body, first = _start(resp)
    owner.post(f"/links/{data['uid']}/revoke", data={"_csrf": csrf})
    assert first + _rest(body) < BIG
    assert last_audit(app, "download_cut")["detail"].endswith(" link_closed")      # link=… owner=… motivo


# --------------------------------------------------------------------------- subidas por partes a medias

def _half_upload(app, client, csrf):
    resp = client.post("/api/uploads", json={"root": "home", "path": "", "name": "a.bin", "size": 10},
                       headers={"X-CSRF-Token": csrf, "Accept": "application/json"})
    assert resp.status_code == 201
    upload_id = resp.get_json()["id"]
    client.put(f"/api/uploads/{upload_id}?offset=0", data=b"12345", content_type="application/octet-stream",
               headers={"X-CSRF-Token": csrf, "Accept": "application/json"})
    with app.app_context():
        row = uploads_repo.get(get_db(), upload_id)
    return row, uploads_core.part_path(__import__("pathlib").Path(row["dir_path"]), upload_id)


def test_half_uploads_go_away_with_the_account(app, home):
    home.mkdir(parents=True)
    client, csrf = signed_in(app)
    row, part = _half_upload(app, client, csrf)
    assert part.exists()
    _disable(app, "ana")
    assert not part.exists()
    with app.app_context():
        assert uploads_repo.get(get_db(), row["id"]) is None


def test_half_uploads_nobody_follows_are_cleaned_every_hour(app, home):
    home.mkdir(parents=True)
    client, csrf = signed_in(app)
    row, part = _half_upload(app, client, csrf)
    with app.app_context():
        get_db().execute("UPDATE uploads SET updated_at = '2000-01-01T00:00:00+00:00'")
        get_db().commit()
        from storageweb.web.context import settings
        assert "upload_cleanup" in maintenance.run_due(get_db(), settings())
    assert not part.exists()


def test_a_page_opened_before_the_session_was_closed(app, home, monkeypatch):
    """Un admin cierra la sesión (o desactiva la cuenta) con la página abierta: su token CSRF se fue con la sesión. Lo
    que envíe esa página no es un ataque: a entrar otra vez (o el 401 para el JavaScript), sin «CSRF no válido» ni
    contar para bloquear la IP, y de vuelta a la página desde la que se hizo."""
    from storageweb.core import ipban
    offenses = []
    monkeypatch.setattr(ipban, "offense", lambda conn, cfg, ip, kind: offenses.append(kind))
    home.mkdir(parents=True)
    (home / "notas.txt").write_text("hola\n", encoding="utf-8")
    client, csrf = signed_in(app)
    with app.app_context():
        get_db().execute("DELETE FROM sessions")
        get_db().commit()
    resp = client.post("/edit/home/notas.txt", data={"_csrf": csrf, "content": "cambiado", "version": "x"},
                       headers={"Referer": "http://localhost/edit/home/notas.txt"})
    assert resp.status_code == 302 and "/login?next=/edit/home/notas.txt" in resp.location
    other, csrf = signed_in(app, create=False)                         # otra pestaña: el JavaScript de la página
    with app.app_context():
        get_db().execute("DELETE FROM sessions")
        get_db().commit()
    js = other.post("/favorites", data={"root": "home", "path": ""},
                    headers={"X-CSRF-Token": csrf, "Accept": "application/json"})
    assert js.status_code == 401 and js.headers[REASON] == "signed_out"
    assert offenses == [] and last_audit(app, "csrf_rejected") is None
    # Sin sesión de antes (otra web que envía un formulario), el CSRF sigue funcionando como siempre
    stranger = app.test_client()
    assert stranger.post("/favorites", data={"root": "home", "path": ""}).status_code == 400
    assert offenses == ["csrf"]

"""Subidas por partes (chunked/reanudables) y descargas parciales (Range)."""
import json
from collections import namedtuple

import pytest

from storageweb.core import uploads as core
from storageweb.db.repositories import uploads as repo

from tests.helpers import add_user, get_csrf, login
from storageweb.web.context import get_db

API = "/api/uploads"


def api(client, token, method, url, body=None, **kw):
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    if isinstance(body, (bytes, bytearray)):
        return client.open(url, method=method, data=bytes(body), headers=headers,
                           content_type="application/octet-stream", **kw)
    return client.open(url, method=method, data=json.dumps(body) if body is not None else None,
                       headers=headers, content_type="application/json", **kw)


def init(client, token, name="grande.bin", size=10, root="home", path=""):
    return api(client, token, "POST", API, {"root": root, "path": path, "name": name, "size": size})


def upload_all(client, token, data: bytes, chunk: int, **kw):
    resp = init(client, token, size=len(data), **kw)
    assert resp.status_code == 201, resp.get_json()
    uid = resp.get_json()["id"]
    for off in range(0, len(data), chunk):
        r = api(client, token, "PUT", f"{API}/{uid}?offset={off}", data[off:off + chunk])
        assert r.status_code == 200, r.get_json()
    return uid, api(client, token, "POST", f"{API}/{uid}/complete")


def test_full_chunked_upload(app, logged, home):
    client, token = logged
    data = bytes(range(256)) * 4000  # ~1 MB
    uid, resp = upload_all(client, token, data, chunk=100_000)
    assert resp.status_code == 200 and resp.get_json() == {"name": "grande.bin", "size": len(data)}
    assert (home / "grande.bin").read_bytes() == data
    assert [p.name for p in home.iterdir()] == ["grande.bin"]  # sin .part
    with app.app_context():
        assert repo.get(get_db(), uid) is None


def test_file_bigger_than_request_limit(app, logged, home):
    """max_upload_mb=5 en los tests: un archivo de 7 MB entra porque va por partes."""
    client, token = logged
    data = b"\x01" * (7 * core.MB)
    chunk = init(client, token, size=len(data)).get_json()["chunk_size"]
    assert chunk < 5 * core.MB
    _, resp = upload_all(client, token, data, chunk=chunk, name="siete.bin")
    assert resp.status_code == 200
    assert (home / "siete.bin").stat().st_size == len(data)


def test_zero_byte_file(logged, home):
    client, token = logged
    uid = init(client, token, name="vacio.txt", size=0).get_json()["id"]
    assert api(client, token, "POST", f"{API}/{uid}/complete").status_code == 200
    assert (home / "vacio.txt").read_bytes() == b""


def test_resume_status_and_wrong_offset(logged):
    client, token = logged
    uid = init(client, token, size=10).get_json()["id"]
    api(client, token, "PUT", f"{API}/{uid}?offset=0", b"12345")
    st = api(client, token, "GET", f"{API}/{uid}").get_json()
    assert st["received"] == 5 and st["size"] == 10 and st["name"] == "grande.bin"
    # El cliente reintenta una parte ya enviada: 409 con el offset correcto
    r = api(client, token, "PUT", f"{API}/{uid}?offset=0", b"12345")
    assert r.status_code == 409 and r.get_json()["received"] == 5
    assert api(client, token, "PUT", f"{API}/{uid}?offset=5", b"67890").get_json()["received"] == 10


def test_more_data_than_declared(logged, home):
    client, token = logged
    uid = init(client, token, size=4).get_json()["id"]
    r = api(client, token, "PUT", f"{API}/{uid}?offset=0", b"123456")
    assert r.status_code == 400
    assert api(client, token, "GET", f"{API}/{uid}").get_json()["received"] == 0


def test_complete_incomplete(logged):
    client, token = logged
    uid = init(client, token, size=10).get_json()["id"]
    api(client, token, "PUT", f"{API}/{uid}?offset=0", b"123")
    r = api(client, token, "POST", f"{API}/{uid}/complete")
    assert r.status_code == 409 and r.get_json()["received"] == 3


def test_missing_offset(logged):
    client, token = logged
    uid = init(client, token, size=3).get_json()["id"]
    assert api(client, token, "PUT", f"{API}/{uid}", b"123").status_code == 400


def test_duplicate_name_and_sanitized(logged, home):
    client, token = logged
    (home / "a.txt").write_text("viejo")
    _, resp = upload_all(client, token, b"nuevo", chunk=5, name="../../a.txt")
    assert resp.get_json()["name"] == "a (1).txt"
    assert (home / "a.txt").read_text() == "viejo"


def test_invalid_requests(logged):
    client, token = logged
    assert init(client, token, name="..").status_code == 400
    assert init(client, token, size=-1).status_code == 400
    assert init(client, token, size="mucho").status_code == 400
    assert init(client, token, root="no-existe").status_code == 404
    assert init(client, token, path="../..").status_code == 404
    assert init(client, token, path="no/existe").status_code == 404


def test_max_file_size(make_app):
    app = make_app({"storage": {"max_file_size_mb": 1}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    assert init(client, token, size=core.MB).status_code == 201
    r = init(client, token, size=core.MB + 1)
    assert r.status_code == 413 and "máximo" in r.get_json()["error"]
    assert "máx. 1 MB por archivo" in client.get("/f/home/").get_data(as_text=True)


def test_unlimited_size_shown(logged):
    client, _ = logged
    assert "sin límite de tamaño" in client.get("/f/home/").get_data(as_text=True)


def test_not_enough_space(logged, monkeypatch):
    client, token = logged
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(core.shutil, "disk_usage", lambda p: Usage(100, 90, 10 * core.MB))
    r = init(client, token, size=core.MB)
    assert r.status_code == 507


def test_requires_login_and_csrf(app, client, logged):
    c, token = logged
    uid = init(c, token, size=3).get_json()["id"]
    anon = app.test_client()
    assert anon.post(API, json={"root": "home", "name": "x", "size": 1}).status_code in (400, 401)
    r = c.put(f"{API}/{uid}?offset=0", data=b"123", content_type="application/octet-stream")
    assert r.status_code == 400  # sin cabecera CSRF


def test_other_user_cannot_touch_upload(app, logged):
    client, token = logged
    uid = init(client, token, size=3).get_json()["id"]
    add_user(app, "beto")
    other = app.test_client()
    login(other, "beto")
    tok = get_csrf(other, "/f/home/")
    assert api(other, tok, "GET", f"{API}/{uid}").status_code == 404
    assert api(other, tok, "PUT", f"{API}/{uid}?offset=0", b"123").status_code == 404
    assert api(other, tok, "POST", f"{API}/{uid}/complete").status_code == 404
    assert api(other, tok, "DELETE", f"{API}/{uid}").status_code == 404


def test_cancel(app, logged, home):
    client, token = logged
    uid = init(client, token, size=10).get_json()["id"]
    api(client, token, "PUT", f"{API}/{uid}?offset=0", b"123")
    assert api(client, token, "DELETE", f"{API}/{uid}").status_code == 204
    assert list(home.iterdir()) == []
    assert api(client, token, "GET", f"{API}/{uid}").status_code == 404


def test_part_files_hidden_in_listing(logged):
    client, token = logged
    init(client, token, name="en-curso.bin", size=10)
    html = client.get("/f/home/").get_data(as_text=True)
    assert ".sw-upload" not in html and "Carpeta vacía" in html


def test_stale_uploads_cleaned(app, logged, home):
    client, token = logged
    old = init(client, token, size=10).get_json()["id"]
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE uploads SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (old,))
        conn.commit()
    init(client, token, size=10)  # dispara la limpieza
    with app.app_context():
        assert repo.get(get_db(), old) is None
    assert not core.part_path(home, old).exists()


def test_permission_revoked_mid_upload(make_app, tmp_path):
    (tmp_path / "comun").mkdir()
    share = {"name": "comun", "path": str(tmp_path / "comun"), "users": ["*"]}
    app = make_app({"storage": {"shares": [share]}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    uid = init(client, token, root="comun", size=6).get_json()["id"]
    api(client, token, "PUT", f"{API}/{uid}?offset=0", b"123")

    # El admin convierte la carpeta en solo lectura a mitad de la subida
    from storageweb.settings import runtime_view
    from storageweb.web.context import runtime, settings
    with app.test_request_context():
        new = runtime_view(settings())
        new["storage"] = {**new["storage"], "shares": [{**share, "read_only": True}]}
        runtime().save(get_db(), new, "root")
    assert api(client, token, "PUT", f"{API}/{uid}?offset=3", b"456").status_code == 403


@pytest.mark.parametrize("perm_app", [{"permissions": {"user": {"upload": False}}}])
def test_upload_permission_required(make_app, perm_app):
    app = make_app(perm_app)
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    assert init(client, token).status_code == 403


def test_read_only_share(make_app, tmp_path):
    (tmp_path / "docs").mkdir()
    app = make_app({"storage": {"shares": [{"name": "docs", "path": str(tmp_path / "docs"),
                                            "read_only": True, "users": ["*"]}]}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    token = get_csrf(client, "/f/home/")
    assert init(client, token, root="docs").status_code == 403


def test_upload_audited(app, logged):
    from storageweb.db.repositories import audit

    client, token = logged
    upload_all(client, token, b"hola", chunk=4, name="x.txt")
    with app.app_context():
        row = audit.recent(get_db(), 1, action="upload")[0]
    assert row["target"] == "home:/x.txt" and row["detail"] == "4"


# --------------------------------------------------------------------------- descargas

def test_download_supports_range(logged, home):
    client, _ = logged
    (home / "datos.bin").write_bytes(b"0123456789")
    resp = client.get("/download/home/datos.bin", headers={"Range": "bytes=4-7"})
    assert resp.status_code == 206
    assert resp.data == b"4567"
    assert resp.headers["Content-Range"] == "bytes 4-7/10"
    assert resp.headers["Accept-Ranges"] == "bytes"


def test_download_is_streamed(logged, home):
    client, _ = logged
    (home / "grande.bin").write_bytes(b"x" * (3 * core.MB))
    resp = client.get("/download/home/grande.bin", buffered=False)
    assert resp.status_code == 200 and resp.is_streamed
    assert int(resp.headers["Content-Length"]) == 3 * core.MB
    resp.close()

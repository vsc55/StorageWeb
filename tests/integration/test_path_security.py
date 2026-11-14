"""Ataques de rutas y de permisos contra todas las operaciones de archivos, en disco y en remoto.

Cada carpeta compartida (disco local, S3, SFTP, FTP, WebDAV) tiene un fichero ``SECRETO`` justo fuera de
su raíz. Ninguna petición puede leerlo, listarlo, cambiarlo ni dejar nada fuera de la raíz.
"""
import io
import json

import pytest

from storageweb.core import backends

from tests.fakes import FakeFTP, FakeS3, FakeSFTPSession, fake_webdav_client
from tests.helpers import add_user, get_csrf, login

SECRET = b"SECRETO-NO-DEBE-SALIR"

# Rutas maliciosas tal como irían en la URL (algunas codificadas)
EVIL_PATHS = [
    "../secreto.txt", "..%2fsecreto.txt", "%2e%2e/secreto.txt", "%2e%2e%2fsecreto.txt", "..%5csecreto.txt",
    "a/../../secreto.txt", "docs/../../secreto.txt", "%2fetc%2fpasswd", "/etc/passwd", "C:%5cWindows%5cwin.ini",
    "secreto.txt%00.png", "x%0d%0aDELE%20secreto.txt", "%252e%252e/secreto.txt", "..;/secreto.txt",
]
# Nombres maliciosos para subir, crear carpetas y renombrar
EVIL_NAMES = ["../../secreto.txt", "..\\..\\secreto.txt", "/etc/cron.d/x", "C:\\x", "..", ".", "a/b",
              ".sw-upload-x.part", "con\x00nul", "linea\r\nDELE x"]


@pytest.fixture
def world(make_app, tmp_path, monkeypatch):
    """App con una carpeta por tipo de almacenamiento, cada una con un secreto fuera de su raíz."""
    # disco local: secreto en la carpeta de arriba
    (tmp_path / "shares" / "local" / "docs").mkdir(parents=True)
    (tmp_path / "shares" / "secreto.txt").write_bytes(SECRET)
    (tmp_path / "shares" / "solo-lectura").mkdir()
    (tmp_path / "shares" / "privada").mkdir()
    (tmp_path / "shares" / "privada" / "de-beto.txt").write_bytes(SECRET)
    # S3: secreto en otro prefijo del mismo bucket
    s3 = FakeS3()
    s3.put("sw/carpeta/docs/", b"")
    s3.put("sw/secreto.txt", SECRET)
    # SFTP, FTP y WebDAV: secreto en la carpeta de arriba del servidor
    remotes = {}
    for kind in ("sftp", "ftp", "webdav"):
        root = tmp_path / f"remoto-{kind}"
        (root / "srv" / "carpeta" / "docs").mkdir(parents=True)
        (root / "srv" / "secreto.txt").write_bytes(SECRET)
        remotes[kind] = root
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "s3", lambda loc: s3)
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "sftp", lambda loc: FakeSFTPSession(remotes["sftp"]))
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "ftp", lambda loc: backends.TYPES["ftp"].connect(loc).__class__(
        loc, ftp_class=FakeFTP(remotes["ftp"])))
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "webdav",
                        lambda loc: fake_webdav_client(remotes["webdav"], {"url": "https://dav.example/dav/"}))
    backends.clear_clients()
    everyone = {"users": ["*"]}
    app = make_app({"storage": {
        "create_shares": False,
        "locations": [
            {"name": "s3", "type": "s3", "bucket": "bucket", "prefix": "sw"},
            {"name": "sftp", "type": "sftp", "host": "h", "username": "u", "path": "/srv"},
            {"name": "ftp", "type": "ftp", "host": "h", "path": "/srv", "tls": False},
            {"name": "webdav", "type": "webdav", "url": "https://dav.example/dav/", "path": "srv"},
        ],
        "shares": [
            {"name": "local", "path": str(tmp_path / "shares" / "local"), **everyone},
            {"name": "s3", "location": "s3", "path": "carpeta", **everyone},
            {"name": "sftp", "location": "sftp", "path": "carpeta", **everyone},
            {"name": "ftp", "location": "ftp", "path": "carpeta", **everyone},
            {"name": "webdav", "location": "webdav", "path": "carpeta", **everyone},
            {"name": "lectura", "path": str(tmp_path / "shares" / "solo-lectura"), "read_only": True, **everyone},
            {"name": "privada", "path": str(tmp_path / "shares" / "privada"), "users": ["beto"]},
        ]}})
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")

    def snapshot():
        """Todo lo que hay FUERA de las raíces de las carpetas (debe quedar igual)."""
        state = {"s3": {k: v[0] for k, v in s3.objects.items() if not k.startswith("sw/carpeta/")}}
        for kind, root in remotes.items():
            state[kind] = sorted((str(p.relative_to(root)), p.read_bytes() if p.is_file() else b"")
                                 for p in root.rglob("*") if "carpeta" not in p.relative_to(root).parts)
        state["local"] = sorted((str(p.relative_to(tmp_path / "shares")), p.read_bytes() if p.is_file() else b"")
                                for p in (tmp_path / "shares").rglob("*")
                                if p.relative_to(tmp_path / "shares").parts[0] != "local")
        return state

    yield app, client, token, snapshot
    backends.clear_clients()


ROOTS = ["local", "s3", "sftp", "ftp", "webdav"]


def _no_secret(resp, root):
    assert SECRET not in resp.get_data(), resp.request.path
    assert resp.status_code in (302, 308, 400, 403, 404), (resp.request.path, resp.status_code)
    if resp.status_code == 308:  # «//» → «/» (Werkzeug): la redirección sigue dentro de la misma carpeta
        assert f"/{root}/" in resp.location and ".." not in resp.location, resp.location


@pytest.mark.parametrize("root", ROOTS)
def test_read_attacks(world, root):
    _app, client, _token, snapshot = world
    before = snapshot()
    for evil in EVIL_PATHS:
        for url in (f"/f/{root}/{evil}", f"/download/{root}/{evil}", f"/f/{root}/docs/{evil}"):
            resp = client.get(url, headers={"Range": "bytes=0-"})
            _no_secret(resp, root)
            assert resp.status_code != 200 or url.startswith("/f/"), url
        resp = client.get(f"/f/{root}/{evil}", headers={"Accept": "application/json"})
        assert SECRET not in resp.get_data()
    assert snapshot() == before


@pytest.mark.parametrize("root", ROOTS)
def test_write_attacks(world, root):
    _app, client, token, snapshot = world
    before = snapshot()
    for evil in EVIL_PATHS:
        client.post(f"/upload/{root}/{evil}", data={"_csrf": token, "files": (io.BytesIO(b"x"), "a.txt")},
                    content_type="multipart/form-data")
        client.post(f"/mkdir/{root}/{evil}", data={"_csrf": token, "name": "nueva"})
        client.post(f"/rename/{root}/{evil}", data={"_csrf": token, "name": "renombrado"})
        client.post(f"/delete/{root}/{evil}", data={"_csrf": token})
    for name in EVIL_NAMES:
        client.post(f"/upload/{root}/docs", data={"_csrf": token, "files": (io.BytesIO(b"x"), name)},
                    content_type="multipart/form-data")
        client.post(f"/mkdir/{root}/docs", data={"_csrf": token, "name": name})
    # Renombrar algo legítimo a un nombre malicioso
    client.post(f"/mkdir/{root}/docs", data={"_csrf": token, "name": "victima"})
    for name in EVIL_NAMES:
        client.post(f"/rename/{root}/docs/victima", data={"_csrf": token, "name": name})
    assert snapshot() == before
    # Lo que se subió con nombres raros quedó dentro, saneado
    listing = client.get(f"/f/{root}/docs", headers={"Accept": "application/json"}).get_json()
    assert len(listing["entries"]) >= 3  # se subieron (saneados) y se creó «victima»: el ataque se ejecutó de verdad
    assert all("/" not in e["name"] and "\\" not in e["name"] and e["name"] not in (".", "..")
               for e in listing["entries"])


@pytest.mark.parametrize("root", ROOTS)
def test_chunked_upload_attacks(world, root):
    _app, client, token, snapshot = world
    before = snapshot()
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    for evil in ["..", "../..", "docs/../..", "/etc", "C:\\Windows", "a\x00b", "docs\r\nDELE x"]:
        resp = client.post("/api/uploads", data=json.dumps({"root": root, "path": evil, "name": "a.txt", "size": 1}),
                           headers=headers, content_type="application/json")
        assert resp.status_code in (400, 404), (evil, resp.status_code)
    for name in EVIL_NAMES:
        resp = client.post("/api/uploads", data=json.dumps({"root": root, "path": "docs", "name": name, "size": 1}),
                           headers=headers, content_type="application/json")
        if resp.status_code == 201:
            uid = resp.get_json()["id"]
            client.put(f"/api/uploads/{uid}?offset=0", data=b"x", headers=headers,
                       content_type="application/octet-stream")
            done = client.post(f"/api/uploads/{uid}/complete", headers=headers).get_json()
            assert "/" not in done["name"] and "\\" not in done["name"]
    # Identificadores de subida inventados o con rutas
    for uid in ("../../secreto", "..%2f..%2fsecreto", "0" * 32):
        assert client.put(f"/api/uploads/{uid}?offset=0", data=b"x", headers=headers,
                          content_type="application/octet-stream").status_code == 404
    assert snapshot() == before


def test_permission_escalation(world, make_app):
    app, client, token, snapshot = world
    before = snapshot()
    # Carpeta de solo lectura: nada que no sea descargar
    assert client.post("/upload/lectura/", data={"_csrf": token, "files": (io.BytesIO(b"x"), "a.txt")},
                       content_type="multipart/form-data").status_code == 403
    assert client.post("/mkdir/lectura/", data={"_csrf": token, "name": "x"}).status_code == 403
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    assert client.post("/api/uploads", data=json.dumps({"root": "lectura", "path": "", "name": "a", "size": 1}),
                       headers=headers, content_type="application/json").status_code == 403
    # Carpeta de otro usuario: ni se ve ni se puede abrir
    assert client.get("/f/privada/").status_code == 404
    assert client.get("/download/privada/de-beto.txt").status_code == 404
    assert b"privada" not in client.get("/f/home/").get_data()
    # Sin CSRF no se escribe
    assert client.post("/mkdir/local/docs", data={"name": "sin-csrf"}).status_code == 400
    # La subida de otro usuario no se puede continuar ni completar
    uid = client.post("/api/uploads", data=json.dumps({"root": "home", "path": "", "name": "a.txt", "size": 3}),
                      headers=headers, content_type="application/json").get_json()["id"]
    add_user(app, "beto")
    other = app.test_client()
    login(other, "beto")
    other_headers = {"X-CSRF-Token": get_csrf(other, "/f/home/"), "Accept": "application/json"}
    assert other.put(f"/api/uploads/{uid}?offset=0", data=b"abc", headers=other_headers,
                     content_type="application/octet-stream").status_code == 404
    assert other.post(f"/api/uploads/{uid}/complete", headers=other_headers).status_code == 404
    # Su carpeta personal es la suya, aunque intente la de ana
    assert other.get("/download/home/../ana/a.txt").status_code == 404
    assert snapshot() == before


def test_malicious_server_names_are_hidden(world):
    """Un servidor remoto (comprometido o malicioso) no puede colar «..», «a\b» ni nombres con control."""
    _app, client, _token, _snapshot = world
    s3 = backends.CLIENT_FACTORIES["s3"]({})
    for key in ("sw/carpeta/docs/../secreto.txt", "sw/carpeta/docs/./x", "sw/carpeta/docs/bien.txt",
                "sw/carpeta/docs/mal\\nombre", "sw/carpeta/docs/ctrl\x01.txt", "sw/carpeta/docs/salto\n.txt"):
        s3.put(key, SECRET)
    resp = client.get("/f/s3/docs", headers={"Accept": "application/json"})
    names = [e["name"] for e in resp.get_json()["entries"]]
    assert "bien.txt" in names
    assert all(n not in (".", "..") and "\\" not in n and "\x01" not in n and "\n" not in n for n in names), names

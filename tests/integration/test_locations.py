"""Carpetas en ubicaciones externas (S3 y SMB con clientes falsos) y su administración."""
import json

import pytest

from storageweb.core import backends
from storageweb.db.repositories import audit
from storageweb.web.context import get_db, settings

from tests.fakes import FakeS3, FakeSMB
from tests.helpers import add_user, get_csrf, login, visible

S3_LOC = {"name": "s3", "label": "Bucket", "type": "s3", "bucket": "bucket", "prefix": "sw",
          "access_key": "AK", "secret_key": "SECRETO"}
NAS_LOC = {"name": "nas", "label": "NAS", "type": "smb", "server": "nas", "share": "files", "path": "sw",
           "username": "u", "password": "CLAVE"}


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "s3", lambda loc: fake)
    backends.clear_clients()
    yield fake
    backends.clear_clients()


@pytest.fixture
def nas(monkeypatch, tmp_path):
    root = tmp_path / "smb"
    (root / "nas" / "files" / "sw").mkdir(parents=True)
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "smb", lambda loc: FakeSMB(root))
    backends.clear_clients()
    yield root / "nas" / "files" / "sw"
    backends.clear_clients()


def _storage(**extra):
    return {"storage": {"locations": [S3_LOC, NAS_LOC], "create_shares": True, **extra}}


def _api(client, token, method, url, body=None):
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    if isinstance(body, bytes):
        return client.open(url, method=method, data=body, headers=headers, content_type="application/octet-stream")
    return client.open(url, method=method, data=json.dumps(body) if body is not None else None, headers=headers,
                       content_type="application/json")


def test_shared_folder_in_s3(make_app, s3, nas):
    app = make_app(_storage(shares=[{"name": "docs", "label": "Docs", "location": "s3", "path": "docs"}]))
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")

    # La carpeta se crea en el bucket al entrar (create_shares) y se puede usar como cualquier otra
    assert client.get("/f/docs/").status_code == 200
    assert "sw/docs/" in s3.objects
    client.post("/mkdir/docs/", data={"_csrf": token, "name": "informes"})
    assert "sw/docs/informes/" in s3.objects
    from io import BytesIO
    r = client.post("/upload/docs/informes", data={"_csrf": token, "files": (BytesIO(b"hola mundo"), "a.txt")},
                    content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert r.get_json() == {"saved": ["a.txt"], "errors": []}
    assert s3.objects["sw/docs/informes/a.txt"][0] == b"hola mundo"
    listing = client.get("/f/docs/informes", headers={"Accept": "application/json"}).get_json()
    assert [(e["name"], e["size"]) for e in listing["entries"]] == [("a.txt", 10)]

    # Descarga completa y por rangos (reanudar, vídeo)
    r = client.get("/download/docs/informes/a.txt")
    assert r.status_code == 200 and r.data == b"hola mundo" and r.headers["Content-Length"] == "10"
    assert "attachment" in r.headers["Content-Disposition"]
    r = client.get("/download/docs/informes/a.txt", headers={"Range": "bytes=5-"})
    assert r.status_code == 206 and r.data == b"mundo" and r.headers["Content-Range"] == "bytes 5-9/10"

    # Subida por partes: el .part está en <data_dir>/uploads y al terminar se envía al bucket
    data = bytes(range(256)) * 100
    uid = _api(client, token, "POST", "/api/uploads",
               {"root": "docs", "path": "informes", "name": "a.txt", "size": len(data)}).get_json()["id"]
    for off in range(0, len(data), 10000):
        assert _api(client, token, "PUT", f"/api/uploads/{uid}?offset={off}", data[off:off + 10000]).status_code == 200
    r = _api(client, token, "POST", f"/api/uploads/{uid}/complete")
    assert r.get_json() == {"name": "a (1).txt", "size": len(data)}
    assert s3.objects["sw/docs/informes/a (1).txt"][0] == data
    with app.app_context():
        assert not list(backends.staging_dir(settings()).glob("*.part"))

    # Renombrar y borrar (carpeta con contenido)
    client.post("/rename/docs/informes/a.txt", data={"_csrf": token, "name": "b.txt"})
    assert "sw/docs/informes/b.txt" in s3.objects and "sw/docs/informes/a.txt" not in s3.objects
    client.post("/delete/docs/informes", data={"_csrf": token})
    assert not [k for k in s3.objects if k.startswith("sw/docs/informes")]
    with app.app_context():
        actions = [r["action"] for r in audit.recent(get_db(), 20)]
    assert {"upload", "download", "mkdir", "rename", "delete"} <= set(actions)


def test_personal_folders_in_smb(make_app, s3, nas):
    app = make_app(_storage(home_location="nas", home_template="homes/{username}"))
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    token = get_csrf(client, "/f/home/")
    from io import BytesIO
    client.post("/upload/home/", data={"_csrf": token, "files": (BytesIO(b"x"), "nota.txt")},
                content_type="multipart/form-data")
    assert (nas / "homes" / "ana" / "nota.txt").read_bytes() == b"x"
    assert client.get("/download/home/nota.txt").data == b"x"


def test_unreachable_location_only_breaks_its_folder(make_app, s3, nas):
    app = make_app(_storage(shares=[{"name": "docs", "label": "Docs", "location": "s3", "path": "docs"}]))
    add_user(app, "ana")
    client = app.test_client()
    login(client, "ana")
    s3.fail = "AccessDenied"
    r = client.get("/f/docs/")
    assert r.status_code == 404 and "S3 ha denegado el acceso" in r.get_data(as_text=True)
    assert client.get("/f/home/").status_code == 200


def test_admin_manages_locations(make_app, s3, nas):
    app = make_app({"storage": {"create_shares": True}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    token = get_csrf(client, "/admin/storage/")
    assert "No hay ubicaciones de almacenamiento" in client.get("/admin/storage/").get_data(as_text=True)
    # Sin ubicaciones, la carpeta nueva ya ofrece dónde guardar (solo el disco) y cómo añadir una
    page = client.get("/admin/access/folders/new").get_data(as_text=True)
    assert 'name="location"' in page and "Disco del servidor" in page and "añade una ubicación" in page
    assert 'name="home_location"' in client.get("/admin/settings/storage").get_data(as_text=True)

    form = {"_csrf": token, "type": "s3", "name": "s3", "label": "Bucket", "bucket": "bucket", "prefix": "",
            "region": "", "endpoint_url": "", "access_key": "AK", "secret_key": "SECRETO"}
    r = client.post("/admin/storage/new", data=form)
    assert r.status_code == 302
    with app.app_context():
        loc = settings()["storage"]["locations"][0]
    assert loc["secret_key"] == "SECRETO" and loc["path_style"] is False

    # El secreto no se muestra y, vacío, se conserva
    page = client.get("/admin/storage/s3").get_data(as_text=True)
    assert "SECRETO" not in page and "(sin cambios)" in page
    client.post("/admin/storage/s3", data={**form, "secret_key": "", "label": "Bucket 2", "then": "test"})
    with app.app_context():
        loc = settings()["storage"]["locations"][0]
    assert loc["secret_key"] == "SECRETO" and loc["label"] == "Bucket 2"
    assert "La conexión con «Bucket 2» funciona" in client.get("/admin/storage/s3").get_data(as_text=True)

    s3.fail = "InvalidAccessKeyId"
    client.post("/admin/storage/s3/test", data={"_csrf": token})
    assert "ha fallado" in client.get("/admin/storage/s3").get_data(as_text=True)

    # Usarla en una carpeta compartida; no se puede quitar mientras la use
    r = client.post("/admin/access/folders/new", data={"_csrf": token, "name": "docs", "label": "Docs",
                                                       "location": "s3", "path": "docs", "add_kind": "all"})
    assert r.status_code == 302
    folders = client.get("/admin/access/folders").get_data(as_text=True)
    assert "s3://bucket/docs" in folders
    client.post("/admin/storage/s3/delete", data={"_csrf": token})
    with app.app_context():
        assert len(settings()["storage"]["locations"]) == 1
    assert "La usan: Docs" in client.get("/admin/storage/s3").get_data(as_text=True)

    # Carpetas personales en la ubicación (página Carpetas personales)
    assert 'name="home_location"' in client.get("/admin/settings/storage").get_data(as_text=True)

    client.post("/admin/access/folders/docs/delete", data={"_csrf": token})
    client.post("/admin/storage/s3/delete", data={"_csrf": token})
    with app.app_context():
        assert settings()["storage"]["locations"] == []
        actions = {r["action"] for r in audit.recent(get_db(), 30)}
    assert {"location_created", "location_updated", "location_tested", "location_deleted"} <= actions


def test_admin_sftp_location_form(make_app, tmp_path, monkeypatch):
    """Tipo con clave privada (campo de varias líneas, secreto) y ruta absoluta del servidor."""
    from tests.fakes import FakeSFTPSession
    remote = tmp_path / "sftp-remoto"
    remote.mkdir()
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "sftp", lambda loc: FakeSFTPSession(remote))
    backends.clear_clients()
    app = make_app()
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    token = get_csrf(client, "/admin/storage/")
    page = client.get("/admin/storage/new?type=sftp").get_data(as_text=True)
    assert 'name="private_key"' in page and "<textarea" in page and 'name="host_key"' in page
    index = client.get("/admin/storage/").get_data(as_text=True)
    assert "Nueva ubicación" in index and 'href="/admin/storage/new?type=sftp"' in index and "<strong>SFTP</strong>" in index
    assert index.count('class="menu-item"') >= 6                       # un solo botón con un menú de tipos
    form = {"_csrf": token, "type": "sftp", "name": "srv", "label": "Servidor", "host": "files.example",
            "port": "22", "path": "/srv/datos", "host_key": "", "username": "ana", "password": "",
            "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\nCLAVE\n-----END OPENSSH PRIVATE KEY-----"}
    assert client.post("/admin/storage/new", data=form).status_code == 302
    page = client.get("/admin/storage/srv").get_data(as_text=True)
    assert "CLAVE" not in page and "(sin cambios)" in page
    client.post("/admin/storage/srv", data={**form, "private_key": "", "label": "Servidor 2", "then": "test"})
    with app.app_context():
        loc = settings()["storage"]["locations"][0]
    assert "CLAVE" in loc["private_key"] and loc["path"] == "/srv/datos" and loc["label"] == "Servidor 2"
    page = client.get("/admin/storage/srv").get_data(as_text=True)
    assert "ha fallado: La carpeta no existe en el servidor: sftp://ana@files.example/srv/datos" in page
    (remote / "srv" / "datos").mkdir(parents=True)
    client.post("/admin/storage/srv/test", data={"_csrf": token})
    assert "funciona: sftp://ana@files.example/srv/datos" in client.get("/admin/storage/srv").get_data(as_text=True)
    backends.clear_clients()


def test_locations_locked_by_config_file(write_config, s3):
    from storageweb import create_app
    app = create_app(str(write_config(_storage())))
    app.testing = True
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    page = visible(client.get("/admin/storage/").get_data(as_text=True))
    assert "config.json" in page and "Nueva ubicación" not in page
    token = get_csrf(client, "/admin/storage/")
    r = client.post("/admin/storage/s3/delete", data={"_csrf": token})
    assert r.status_code == 302
    with app.app_context():
        assert len(settings()["storage"]["locations"]) == 2
    # El listado de la configuración no enseña los secretos
    with app.app_context():
        from storageweb.settings.loader import mask_secrets
        masked = json.dumps(mask_secrets(settings()))
    assert "SECRETO" not in masked and "CLAVE" not in masked
    # Ni en la lista de valores de Sistema → Información ni en el buscador (se muestran por su nombre)
    with app.app_context():
        from storageweb.settings import fields
        assert fields.display("storage.locations", settings()["storage"]["locations"], limit=10_000) == "s3, nas"

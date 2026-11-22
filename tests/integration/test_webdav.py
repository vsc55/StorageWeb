"""Unidad de red (WebDAV en /dav/): autenticación, permisos, métodos y compatibilidad con un cliente real.

El último test usa el backend WebDAV de StorageWeb (el que conecta ubicaciones externas) como cliente
contra este servidor y le pasa la misma batería que a los demás almacenamientos.
"""
import io

import pytest

from storageweb.db.repositories import audit
from storageweb.web.context import get_db

from tests.helpers import PASSWORD, add_user, signed_in, api_token, basic_auth

PROPFIND = b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:allprop/></d:propfind>'


@pytest.fixture
def dav(make_app, tmp_path):
    shared = tmp_path / "compartida"
    shared.mkdir()
    (shared / "leeme.txt").write_bytes(b"compartido")
    app = make_app({"storage": {"shares": [
        {"name": "equipo", "label": "Equipo", "path": str(shared), "users": ["*"]},
        {"name": "lectura", "path": str(tmp_path / "ro"), "users": ["*"], "read_only": True},
    ], "create_shares": True}})
    add_user(app, "ana")
    client = app.test_client()
    headers = basic_auth("ana", api_token(app, "ana"))

    def call(method, path, data=b"", extra=None, **kw):
        return client.open(path, method=method, data=data, headers={**headers, **(extra or {})}, **kw)
    return app, client, call, tmp_path


def test_auth(dav):
    app, client, call, _tmp = dav
    resp = client.open("/dav/", method="PROPFIND")
    assert resp.status_code == 401 and resp.headers["WWW-Authenticate"].startswith("Basic")
    assert client.open("/dav/", method="OPTIONS").headers["DAV"] == "1, 2"
    assert "DAV" in client.open("/", method="OPTIONS").headers  # Windows pregunta antes en la raíz del sitio
    # La contraseña de la cuenta no vale por defecto; un token de otro usuario tampoco
    assert client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", PASSWORD)).status_code == 401
    add_user(app, "beto")
    assert client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", api_token(app, "beto"))).status_code == 401
    with app.app_context():
        assert audit.recent(get_db(), 1)[0]["detail"] == "webdav:bad_token"
    # Con «Bearer» también (rclone, scripts) y la cookie del navegador no sirve aquí
    plain = api_token(app, "ana")
    assert client.open("/dav/", method="PROPFIND", headers={"Authorization": f"Bearer {plain}"}).status_code == 207
    from tests.helpers import login
    browser = app.test_client()
    login(browser, "ana")
    assert browser.open("/dav/", method="PROPFIND").status_code == 401
    assert call("PROPFIND", "/dav/", PROPFIND, {"Depth": "1"}).status_code == 207


def test_audit_says_which_token(dav):
    """Los cambios por la unidad de red (y la extensión de VS Code, que la usa) dicen con qué token se hicieron."""
    app, _client, call, _tmp = dav
    assert call("PUT", "/dav/equipo/nota.txt", b"hola").status_code == 201
    assert call("MOVE", "/dav/equipo/nota.txt", extra={"Destination": "/dav/equipo/nota2.txt"}).status_code == 201
    assert call("DELETE", "/dav/equipo/nota2.txt").status_code == 204
    with app.app_context():
        details = [(r["action"], r["detail"]) for r in audit.recent(get_db(), 3)]
    assert details == [("delete", "webdav token=dav"), ("rename", "webdav:move:equipo:/nota2.txt token=dav"),
                       ("upload", "webdav:4 token=dav")]


def test_passwords_when_allowed(make_app):
    app = make_app({"security": {"webdav_passwords": True}})
    add_user(app, "ana")
    client = app.test_client()
    for _ in range(3):  # la segunda y la tercera salen de la caché
        assert client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", PASSWORD)).status_code == 207
    assert client.open("/dav/", method="PROPFIND", headers=basic_auth("EQUIPO\\ana", PASSWORD)).status_code == 207
    assert client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", "mala")).status_code == 401
    assert client.open("/dav/home/con-clave.txt", method="PUT", data=b"x",
                       headers=basic_auth("ana", PASSWORD)).status_code == 201
    with app.app_context():                     # con la contraseña de la cuenta no hay token que anotar
        assert audit.recent(get_db(), 1, action="upload")[0]["detail"] == "webdav:1"


def test_disabled(make_app):
    app = make_app({"security": {"webdav": False}})
    add_user(app, "ana")
    assert app.test_client().open("/dav/", method="PROPFIND",
                                  headers=basic_auth("ana", api_token(app, "ana"))).status_code == 404


def test_listing_and_files(dav):
    _app, _client, call, tmp = dav
    resp = call("PROPFIND", "/dav/", PROPFIND, {"Depth": "1"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 207 and "/dav/home/" in body and "/dav/equipo/" in body and "Equipo" in body
    assert call("PROPFIND", "/dav/equipo/", b"", {"Depth": "infinity"}).status_code == 403  # profundidad finita
    body = call("PROPFIND", "/dav/equipo/", PROPFIND, {"Depth": "1"}).get_data(as_text=True)
    assert "/dav/equipo/leeme.txt" in body and "<d:getcontentlength>10</d:getcontentlength>" in body
    # Propiedades pedidas: las que no existen, en un propstat 404
    asked = (b'<d:propfind xmlns:d="DAV:" xmlns:z="urn:x"><d:prop><d:getetag/><z:raro/></d:prop></d:propfind>')
    body = call("PROPFIND", "/dav/equipo/leeme.txt", asked, {"Depth": "0"}).get_data(as_text=True)
    assert "getetag" in body and "404 Not Found" in body and "raro" in body

    # Subir, leer por rangos, sobrescribir, crear carpetas, mover, copiar y borrar
    assert call("PUT", "/dav/home/nota%20%C3%B1.txt", b"hola mundo").status_code == 201
    resp = call("GET", "/dav/home/nota%20%C3%B1.txt", extra={"Range": "bytes=5-"})
    assert resp.status_code == 206 and resp.data == b"mundo"
    assert resp.headers["Content-Security-Policy"] == "sandbox" and "attachment" in resp.headers["Content-Disposition"]
    resp.close()  # en Windows no se puede sustituir un archivo abierto
    head = call("HEAD", "/dav/home/nota%20%C3%B1.txt")
    assert head.data == b"" and head.headers["Content-Length"] == "10"
    head.close()
    assert call("PUT", "/dav/home/nota%20%C3%B1.txt", b"nuevo").status_code == 204
    assert call("MKCOL", "/dav/home/docs").status_code == 201
    assert call("MKCOL", "/dav/home/docs").status_code == 405
    assert call("MKCOL", "/dav/home/no/existe").status_code == 409
    assert call("PUT", "/dav/home/no/existe.txt", b"x").status_code == 409
    home = tmp / "data" / "homes" / "ana"
    dest = {"Destination": "http://localhost/dav/home/docs/nota.txt"}
    assert call("MOVE", "/dav/home/nota%20%C3%B1.txt", extra=dest).status_code == 201
    assert (home / "docs" / "nota.txt").read_bytes() == b"nuevo"
    assert call("COPY", "/dav/home/docs", extra={"Destination": "/dav/home/docs2"}).status_code == 201
    assert (home / "docs2" / "nota.txt").exists()
    assert call("COPY", "/dav/home/docs", extra={"Destination": "/dav/home/docs2", "Overwrite": "F"}).status_code == 412
    assert call("COPY", "/dav/home/docs", extra={"Destination": "/dav/home/docs2"}).status_code == 204
    # Entre carpetas (de la personal a una compartida) y dentro de sí misma no
    assert call("MOVE", "/dav/home/docs2", extra={"Destination": "/dav/equipo/docs2"}).status_code == 201
    assert (tmp / "compartida" / "docs2" / "nota.txt").exists() and not (home / "docs2").exists()
    assert call("MOVE", "/dav/home/docs", extra={"Destination": "/dav/home/docs/dentro"}).status_code == 403
    assert call("DELETE", "/dav/equipo/docs2").status_code == 204
    assert not (tmp / "compartida" / "docs2").exists()
    # Bloqueos simulados: LOCK de algo nuevo lo crea vacío (Office, Windows), PROPPATCH dice que sí
    resp = call("LOCK", "/dav/home/office.docx", b'<d:lockinfo xmlns:d="DAV:"><d:lockscope><d:exclusive/>'
                b"</d:lockscope><d:locktype><d:write/></d:locktype></d:lockinfo>")
    assert resp.status_code == 201 and resp.headers["Lock-Token"].startswith("<opaquelocktoken:")
    assert (home / "office.docx").read_bytes() == b""
    assert call("UNLOCK", "/dav/home/office.docx", extra={"Lock-Token": resp.headers["Lock-Token"]}).status_code == 204
    patch = (b'<d:propertyupdate xmlns:d="DAV:" xmlns:z="urn:schemas-microsoft-com:"><d:set><d:prop>'
             b"<z:Win32LastModifiedTime>x</z:Win32LastModifiedTime></d:prop></d:set></d:propertyupdate>")
    assert call("PROPPATCH", "/dav/home/office.docx", patch).status_code == 207


def test_permissions(make_app, tmp_path):
    app = make_app({"permissions": {"user": {"upload": True, "download": True, "mkdir": True, "rename": False,
                                             "delete": False}},
                    "storage": {"shares": [{"name": "lectura", "path": str(tmp_path / "ro"), "users": ["*"],
                                            "read_only": True}], "create_shares": True}})
    add_user(app, "ana")
    client = app.test_client()
    write, read = basic_auth("ana", api_token(app, "ana")), basic_auth("ana", api_token(app, "ana", scope="read"))

    def call(method, path, headers, data=b"", extra=None):
        return client.open(path, method=method, data=data, headers={**headers, **(extra or {})})
    assert call("PUT", "/dav/home/a.txt", write, b"1").status_code == 201
    assert call("PUT", "/dav/home/a.txt", write, b"2").status_code == 403    # sobrescribir = borrar: sin permiso
    assert call("DELETE", "/dav/home/a.txt", write).status_code == 403
    assert call("MOVE", "/dav/home/a.txt", write, extra={"Destination": "/dav/home/b.txt"}).status_code == 403
    assert call("PUT", "/dav/home/b.txt", read, b"1").status_code == 403     # token de solo lectura
    assert call("GET", "/dav/home/a.txt", read).status_code == 200
    assert call("PUT", "/dav/lectura/x.txt", write, b"1").status_code == 403  # carpeta de solo lectura
    assert call("MKCOL", "/dav/lectura/x", write).status_code == 403
    assert call("COPY", "/dav/home/a.txt", write, extra={"Destination": "/dav/lectura/a.txt"}).status_code == 403


@pytest.mark.parametrize("path", ["/dav/home/../../etc/passwd", "/dav/home/%2e%2e/%2e%2e/x", "/dav/..%2fhome",
                                  "/dav/home/a%00b", "/dav/home/C:%5cWindows", "/dav/otro-usuario/"])
def test_paths_stay_inside(dav, path):
    _app, _client, call, _tmp = dav
    assert call("PROPFIND", path, b"", {"Depth": "0"}).status_code in (400, 404)
    assert call("PUT", path, b"x").status_code in (400, 404, 405)


def test_destination_outside(dav):
    _app, _client, call, tmp = dav
    call("PUT", "/dav/home/a.txt", b"1")
    for dest in ("http://otro.example/dav/home/b.txt", "/files/home/b.txt", "/dav/home/../../fuera.txt",
                 "/dav/home/sub/..%2f..%2f..%2ffuera.txt", "/dav/home/b\x00.txt"):
        assert call("COPY", "/dav/home/a.txt", extra={"Destination": dest}).status_code in (400, 403, 404, 409, 502)
    assert not list(tmp.rglob("fuera.txt"))


def test_our_webdav_client_against_our_server(dav, tmp_path):
    """El backend WebDAV de StorageWeb como cliente de este servidor: la misma batería que los demás."""
    from storageweb.core.backends.webdav import Response, WebDAVBackend, WebDAVClient
    _app, client, _call, _tmp = dav
    plain = api_token(_app, "ana")

    class TestClient(WebDAVClient):
        def send(self, method, url, headers, body=None, stream=False):
            data = body.read() if hasattr(body, "read") else body
            resp = client.open(url.replace("http://localhost", ""), method=method, data=data or b"",
                               headers={**self.headers, **headers})
            return Response(resp.status_code, dict(resp.headers), io.BytesIO(resp.data) if stream else resp.data)

    backend = WebDAVBackend(TestClient({"url": "http://localhost/dav/home/", "username": "ana", "password": plain}),
                            "prueba", tmp_path / "staging")
    from tests.unit import test_backends as battery
    for test in (battery.test_root_and_mkdir, battery.test_store_list_open_and_seek,
                 battery.test_unique_rel_rename_and_delete, battery.test_move_and_copy):
        backend.ensure_root()
        test(backend, tmp_path)
        for entry in backend.listdir(""):
            backend.delete(entry.name)


def test_profile_and_settings(make_app):
    from tests.helpers import login
    app = make_app()
    add_user(app, "ana")
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "ana")
    page = client.get("/profile/drive").get_data(as_text=True)
    assert "Unidad de red" in page and "http://localhost/dav/" in page and "<code>ana</code>" in page
    admin = app.test_client()
    login(admin, "root")
    page = admin.get("/admin/settings/clients").get_data(as_text=True)     # Seguridad → API y unidad de red
    assert 'name="webdav"' in page and 'name="webdav_passwords"' in page


def test_profile_without_webdav(make_app):
    from tests.helpers import login
    app = make_app({"security": {"webdav": False}})
    client, _ = signed_in(app, "ana", csrf_url=None)
    assert "Unidad de red" not in client.get("/profile").get_data(as_text=True)


def test_failures_do_not_lock_the_web_login(make_app):
    """Una unidad mal configurada reintenta sola: no debe dejar al usuario sin entrar en la web."""
    from tests.helpers import login
    app = make_app()
    add_user(app, "ana")
    client = app.test_client()
    # Contraseña de la cuenta con la opción desactivada: no cuenta como intento fallido
    for _ in range(10):
        assert client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", PASSWORD)).status_code == 401
    good = basic_auth("ana", api_token(app, "ana"))
    assert client.open("/dav/", method="PROPFIND", headers=good).status_code == 207
    # Tokens erróneos sí cuentan: bloquean la unidad, pero no el inicio de sesión en la web
    for _ in range(6):
        client.open("/dav/", method="PROPFIND", headers=basic_auth("ana", "sw_malo"))
    assert client.open("/dav/", method="PROPFIND", headers=good).status_code == 401  # bloqueada un rato
    assert login(app.test_client(), "ana").status_code == 302                     # la web, no
    with app.app_context():
        details = {r["detail"] for r in audit.recent(get_db(), 30)}
    assert {"webdav:password_not_allowed", "webdav:bad_token"} <= details


def test_conditional_writes(dav):
    """If-Match / If-None-Match: un cliente no pisa lo que cambió otro."""
    _app, _client, call, _tmp = dav
    resp = call("PUT", "/dav/home/c.txt", b"uno", {"If-None-Match": "*"})
    assert resp.status_code == 201
    v1 = resp.headers["ETag"]
    assert call("PUT", "/dav/home/c.txt", b"otro", {"If-None-Match": "*"}).status_code == 412  # ya existe
    import time
    time.sleep(0.01)
    resp = call("PUT", "/dav/home/c.txt", b"dos", {"If-Match": v1})
    assert resp.status_code == 204 and resp.headers["ETag"] != v1
    assert call("PUT", "/dav/home/c.txt", b"tres", {"If-Match": v1}).status_code == 412      # versión vieja
    assert call("DELETE", "/dav/home/c.txt", extra={"If-Match": v1}).status_code == 412
    assert call("GET", "/dav/home/c.txt").data == b"dos"
    body = call("PROPFIND", "/dav/home/c.txt", b"", {"Depth": "0"}).get_data(as_text=True)
    assert resp.headers["ETag"] in body
    assert call("DELETE", "/dav/home/c.txt", extra={"If-Match": resp.headers["ETag"]}).status_code == 204


def test_hidden_files_are_listed(dav):
    """Los que empiezan por punto se listan aunque la web los oculte: un cliente que sincroniza tiene que
    ver lo que subió (si no, cree que se borró en el servidor)."""
    app, client, call, _tmp = dav
    assert call("PUT", "/dav/home/.gitignore", b"x").status_code == 201
    assert call("MKCOL", "/dav/home/.venv").status_code == 201
    body = call("PROPFIND", "/dav/home/", b"", {"Depth": "1"}).get_data(as_text=True)
    assert "/dav/home/.gitignore" in body and "/dav/home/.venv/" in body
    assert ".sw-upload-" not in body

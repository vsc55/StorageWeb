"""Detalles de los tipos SFTP, FTP, WebDAV y Azure (la batería común está en test_backends.py)."""
import base64
import ftplib
import hashlib
import ssl

import pytest

from storageweb.core import backends, locations
from storageweb.core.backends import BackendError
from storageweb.core.backends.azure import AzureBlobBackend
from storageweb.core.backends.ftp import FTPBackend, FTPConnector
from storageweb.core.backends.ftp import _error as ftp_error
from storageweb.core.backends.sftp import SFTPBackend, host_key_matches
from storageweb.core.backends.sftp import _error as sftp_error
from storageweb.core.backends.webdav import WebDAVBackend, _parse_multistatus
from storageweb.settings import ConfigError, location_types

from tests.fakes import FakeAzureContainer, FakeAzureError, FakeFTP, fake_webdav_client


def test_new_types_are_discovered():
    assert {"sftp", "ftp", "webdav", "azure"} <= set(backends.TYPES)
    assert location_types.get("sftp").secrets == ("password", "private_key")
    assert location_types.get("azure").secrets == ("account_key", "sas_token")


def test_server_paths():
    sftp = location_types.get("sftp")
    assert sftp.normalize({"host": "h", "username": "u", "path": "/srv//datos/"}, "s")["path"] == "/srv/datos"
    assert sftp.normalize({"host": "h", "username": "u", "path": "rel/x"}, "s")["path"] == "rel/x"
    with pytest.raises(ConfigError, match=r"\.\."):
        sftp.normalize({"host": "h", "username": "u", "path": "/srv/../etc"}, "s")
    loc = sftp.normalize({"host": "h", "username": "ana", "path": "/srv/datos", "port": 2222}, "s")
    assert locations.describe(loc, "docs") == "sftp://ana@h:2222/srv/datos/docs"
    assert locations.describe({**loc, "path": "rel", "port": 22}) == "sftp://ana@h/~/rel"
    ftp = location_types.get("ftp").normalize({"host": "f", "path": "/x"}, "f")
    assert ftp["tls"] is True and ftp["verify_tls"] is True and ftp["port"] == 21
    assert locations.describe(ftp) == "ftps://f/x"


def test_host_key_matches():
    key = b"\x00\x00\x00\x0bssh-ed25519clave-del-servidor"
    b64 = base64.b64encode(key).decode()
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
    assert host_key_matches(f"ssh-ed25519 {b64} comentario", "ssh-ed25519", key)
    assert host_key_matches(f"servidor.example ssh-ed25519 {b64}", "ssh-ed25519", key)  # línea de known_hosts
    assert host_key_matches(fingerprint, "ssh-ed25519", key)
    assert not host_key_matches(f"ssh-rsa {b64}", "ssh-ed25519", key)
    assert not host_key_matches("SHA256:otra", "ssh-ed25519", key)


def test_error_messages():
    class AuthenticationException(Exception):
        pass
    assert "rechazado" in sftp_error(AuthenticationException("x")).message
    assert "rechazado" in ftp_error(ftplib.error_perm("530 Login incorrect")).message
    cert = ssl.SSLCertVerificationError(1, "x")
    cert.verify_message = "self-signed certificate"
    message = ftp_error(cert).message
    assert "self-signed certificate" in message and "Comprobar el certificado" in message


def test_ftp_bad_login_and_relative_paths(tmp_path):
    (tmp_path / "home").mkdir()
    bad = FTPBackend(FTPConnector({"host": "f", "username": "malo"}, ftp_class=FakeFTP(tmp_path)), "", tmp_path)
    with pytest.raises(BackendError, match="rechazado"):
        bad.listdir("")
    relative = FTPBackend(FTPConnector({"host": "f"}, ftp_class=FakeFTP(tmp_path)), "home/sw", tmp_path / "st")
    relative.ensure_root()
    relative.mkdir("a")
    assert (tmp_path / "home" / "sw" / "a").is_dir() and relative.is_dir("a")


def test_webdav_parsing_and_requests(tmp_path):
    xml = b'''<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">
      <d:response><d:href>https://nube.example/remote.php/dav/files/ana/Informes%202026/</d:href>
        <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>
          <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
        <d:propstat><d:prop><d:getcontentlength/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>
      </d:response>
      <d:response><d:href>/remote.php/dav/files/ana/a%C3%B1o.pdf</d:href>
        <d:propstat><d:prop><d:resourcetype/><d:getcontentlength>12</d:getcontentlength>
          <d:getlastmodified>Fri, 02 Jan 2026 03:04:05 GMT</d:getlastmodified></d:prop>
          <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'''
    found = dict(_parse_multistatus(xml))
    assert found["/remote.php/dav/files/ana/Informes 2026"].is_dir
    pdf = found["/remote.php/dav/files/ana/año.pdf"]
    assert (pdf.name, pdf.size, pdf.is_dir) == ("año.pdf", 12, False) and pdf.mtime > 0

    client = fake_webdav_client(tmp_path)
    backend = WebDAVBackend(client, "sw", tmp_path / "st")
    backend.ensure_root()
    backend.mkdir("Carpeta ñ")
    assert ("MKCOL", "https://dav.example/remote.php/dav/files/ana/sw/Carpeta%20%C3%B1") in client.requests
    backend.rename("Carpeta ñ", "Otra")
    assert any(m == "MOVE" and u.endswith("/Carpeta%20%C3%B1/") for m, u in client.requests)  # carpetas, con «/»
    assert backend.is_dir("Otra")


def test_azure_errors_and_markers(tmp_path):
    container = FakeAzureContainer()
    backend = AzureBlobBackend(container, "sw", tmp_path)
    backend.ensure_root()
    backend.mkdir("vacia")
    assert set(container.blobs) == {"sw/", "sw/vacia/"} and backend.is_dir("vacia")
    container.fail = FakeAzureError(403, "AuthorizationFailure")
    with pytest.raises(BackendError, match="Azure ha denegado"):
        backend.listdir("")
    container.fail = FakeAzureError(404, "ContainerNotFound")
    with pytest.raises(BackendError, match="contenedor de Azure no existe"):
        backend.stat("x")


def test_missing_libraries(tmp_path, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def without(name, *args, **kwargs):
        if name in ("paramiko", "azure.storage.blob"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without)
    backends.clear_clients()
    sftp = backends.backend_for({"name": "s", "type": "sftp", "host": "h", "username": "u"}, "", tmp_path)
    assert "paramiko" in sftp.message and "storageweb[sftp]" in sftp.message
    azure = backends.backend_for({"name": "a", "type": "azure", "account": "c", "container": "d"}, "", tmp_path)
    assert "azure-storage-blob" in azure.message and "storageweb[azure]" in azure.message
    backends.clear_clients()


def test_sftp_create_paths(tmp_path):
    loc = {"host": "h", "username": "u", "path": "/srv/datos"}
    absolute = SFTPBackend.create(None, loc, "docs", tmp_path)
    assert absolute._p("a/b") == "/srv/datos/docs/a/b"
    relative = SFTPBackend.create(None, {**loc, "path": ""}, "", tmp_path)
    assert relative._p("") == "." and relative._p("x") == "x"


def test_webdav_rejects_entities():
    import xml.etree.ElementTree as ET
    bomb = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><d:multistatus xmlns:d="DAV:"/>'
    with pytest.raises(ET.ParseError):
        _parse_multistatus(bomb)


def test_local_rename_refuses_unsafe_names(tmp_path):
    from storageweb.core.backends import LocalBackend
    from storageweb.core.security import PathError
    (tmp_path / "raiz").mkdir()
    (tmp_path / "raiz" / "a.txt").write_text("x")
    backend = LocalBackend(tmp_path / "raiz", tmp_path / "st")
    for bad in ("../fuera.txt", "..", "sub/b.txt", "c\\d", "", "salto\nlinea"):
        with pytest.raises(PathError):
            backend.rename("a.txt", bad)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["raiz"]

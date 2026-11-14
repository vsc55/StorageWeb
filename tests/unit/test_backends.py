"""Backends de almacenamiento (disco local, S3, SMB, SFTP, FTP, WebDAV, Azure) con la misma batería de pruebas."""
import pytest

from storageweb.core import backends, locations
from storageweb.core.backends import BackendError, LocalBackend, UnavailableBackend
from storageweb.core.backends.s3 import S3Backend
from storageweb.core.backends.smb import SMBBackend
from storageweb.core.security import PathError

from storageweb.core.backends.azure import AzureBlobBackend
from storageweb.core.backends.ftp import FTPBackend, FTPConnector
from storageweb.core.backends.sftp import SFTPBackend
from storageweb.core.backends.webdav import WebDAVBackend

from tests.fakes import (FakeAzureContainer, FakeFTP, FakeS3, FakeSFTPSession, FakeSMB, fake_webdav_client)


@pytest.fixture(params=["local", "s3", "smb", "sftp", "ftp", "ftp-sin-mlsd", "webdav", "azure"])
def backend(request, tmp_path):
    staging = tmp_path / "staging"
    remote = tmp_path / "remoto"
    if request.param == "local":
        (tmp_path / "disk").mkdir()
        return LocalBackend(tmp_path / "disk", staging)
    if request.param == "s3":
        return S3Backend(FakeS3(), "bucket", "pre/fijo", staging)
    if request.param == "smb":
        (tmp_path / "smb" / "nas" / "files" / "base").mkdir(parents=True)
        return SMBBackend(FakeSMB(tmp_path / "smb"), "nas", "files", "base", staging)
    remote.mkdir()
    if request.param == "sftp":
        return SFTPBackend(FakeSFTPSession(remote), "/srv/base", staging)
    if request.param.startswith("ftp"):
        connector = FTPConnector({"host": "ftp", "tls": False},
                                 ftp_class=FakeFTP(remote, mlsd=request.param == "ftp"))
        return FTPBackend(connector, "/datos/base", staging)
    if request.param == "webdav":
        return WebDAVBackend(fake_webdav_client(remote), "carpeta con espacios/base", staging)
    return AzureBlobBackend(FakeAzureContainer(), "pre/fijo", staging)


def _put(backend, tmp_path, rel: str, data: bytes) -> None:
    local = backend.staging_dir("") / "tmp.part"
    local.write_bytes(data)
    backend.store(local, rel)
    assert not local.exists()


def test_root_and_mkdir(backend, tmp_path):
    backend.ensure_root()
    assert backend.root_exists() and backend.is_dir("")
    backend.mkdir("informes")
    assert backend.is_dir("informes") and not backend.is_file("informes")
    with pytest.raises(FileExistsError):
        backend.mkdir("informes")
    assert backend.stat("nada") is None


def test_store_list_open_and_seek(backend, tmp_path):
    backend.ensure_root()
    backend.mkdir("docs")
    data = bytes(range(256)) * 10
    _put(backend, tmp_path, "docs/a.bin", data)
    _put(backend, tmp_path, "docs/b.txt", b"hola")
    backend.mkdir("docs/sub")
    entries = {e.name: e for e in backend.listdir("docs")}
    assert set(entries) == {"a.bin", "b.txt", "sub"}
    assert entries["a.bin"].size == len(data) and not entries["a.bin"].is_dir and entries["sub"].is_dir
    assert entries["a.bin"].mtime > 0
    fh, size, _mtime = backend.open("docs/a.bin")
    with fh:
        assert size == len(data)
        fh.seek(1000)
        assert fh.read(10) == data[1000:1010]
        fh.seek(0)
        assert fh.read() == data
    with pytest.raises(FileNotFoundError):
        backend.open("docs/sub")


def test_unique_rel_rename_and_delete(backend, tmp_path):
    backend.ensure_root()
    _put(backend, tmp_path, "a.txt", b"1")
    assert backend.unique_rel("", "a.txt") == "a (1).txt"
    assert backend.rename("a.txt", "b.txt") == "b.txt"
    assert backend.stat("a.txt") is None and backend.is_file("b.txt")
    backend.mkdir("dir")
    backend.mkdir("dir/sub")
    _put(backend, tmp_path, "dir/sub/x.txt", b"x")
    with pytest.raises(FileExistsError):
        backend.rename("dir", "b.txt")
    backend.rename("dir", "carpeta")
    assert backend.is_file("carpeta/sub/x.txt") and backend.stat("dir") is None
    backend.delete("carpeta")
    assert backend.stat("carpeta") is None and backend.stat("carpeta/sub/x.txt") is None
    assert [e.name for e in backend.listdir("")] == ["b.txt"]


def test_paths_never_leave_the_root(backend):
    for bad in ("../x", "a/../../x", "C:/Windows"):
        with pytest.raises(PathError):
            backend.stat(bad)


def test_clean_rel():
    assert backends.clean_rel("/a//b/./c/") == "a/b/c"
    assert backends.clean_rel("a\\b") == "a/b"
    assert backends.clean_rel("") == ""
    assert backends.join_rel("", "a", "", "b") == "a/b"
    assert backends.parent_rel("a/b/c") == "a/b" and backends.parent_rel("a") == ""


def test_s3_paginates_and_maps_errors(tmp_path):
    s3 = FakeS3(page_size=1)
    backend = S3Backend(s3, "bucket", "", tmp_path)
    for i in range(5):
        s3.put(f"f{i}.txt", b"x")
    s3.put("d/z.txt", b"z")
    assert sorted(e.name for e in backend.listdir("")) == ["d", "f0.txt", "f1.txt", "f2.txt", "f3.txt", "f4.txt"]
    assert backend.is_dir("d")
    s3.fail = "AccessDenied"
    with pytest.raises(BackendError, match="S3"):
        backend.listdir("")
    with pytest.raises(BackendError, match="no existe"):
        S3Backend(FakeS3(), "otro", "", tmp_path).check()


def test_s3_reads_only_from_the_requested_offset(tmp_path):
    s3 = FakeS3()
    s3.put("big.bin", bytes(1000))
    fh, size, _ = S3Backend(s3, "bucket", "", tmp_path).open("big.bin")
    fh.seek(990)
    assert fh.read() == bytes(10) and size == 1000
    assert s3.calls.count("get_object") == 1


def test_unavailable_backend(tmp_path):
    backend = UnavailableBackend("sin conexión", tmp_path)
    assert not backend.root_exists()
    for call in (lambda: backend.listdir(""), lambda: backend.stat("a"), backend.check):
        with pytest.raises(BackendError, match="sin conexión"):
            call()


def test_backend_for_and_client_cache(tmp_path, monkeypatch):
    made = []
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "s3", lambda loc: made.append(loc) or FakeS3(loc["bucket"]))
    backends.clear_clients()
    loc = {"name": "s3", "type": "s3", "bucket": "bucket", "prefix": "base"}
    first = backends.backend_for(loc, "docs", tmp_path)
    assert isinstance(first, S3Backend) and first.prefix == "base/docs"
    backends.backend_for(loc, "otra", tmp_path)
    assert len(made) == 1  # un cliente por ubicación
    backends.backend_for({**loc, "secret_key": "nuevo"}, "", tmp_path)
    assert len(made) == 2  # credenciales nuevas: cliente nuevo

    def broken(_loc):
        raise RuntimeError("DNS")
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "smb", broken)
    failed = backends.backend_for({"name": "nas", "type": "smb", "server": "x", "share": "y"}, "", tmp_path)
    assert isinstance(failed, UnavailableBackend) and "DNS" in failed.message
    assert locations.test({"data_dir": str(tmp_path)}, {"name": "nas", "type": "smb", "server": "x",
                                                         "share": "y"})
    backends.clear_clients()


def test_missing_library_is_reported(tmp_path, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_boto(name, *args, **kwargs):
        if name in ("boto3", "smbclient"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_boto)
    backends.clear_clients()
    backend = backends.backend_for({"name": "s3", "type": "s3", "bucket": "b"}, "", tmp_path)
    assert isinstance(backend, UnavailableBackend) and "boto3" in backend.message
    backend = backends.backend_for({"name": "nas", "type": "smb", "server": "s", "share": "x"}, "", tmp_path)
    assert isinstance(backend, UnavailableBackend) and "smbprotocol" in backend.message


def test_locations_helpers():
    s3 = {"name": "s3", "label": "S3", "type": "s3", "bucket": "b", "prefix": "p"}
    nas = {"name": "nas", "label": "NAS", "type": "smb", "server": "srv", "share": "files", "path": "sw"}
    assert locations.describe(s3, "docs") == "s3://b/p/docs"
    assert locations.describe(nas) == "\\\\srv\\files\\sw"
    cfg = {"storage": {"locations": [s3, nas], "home_location": "nas",
                       "shares": [{"name": "docs", "label": "Docs", "location": "s3", "path": "docs"}]}}
    assert locations.where(cfg, "s3", "docs") == "s3://b/p/docs"
    assert locations.where(cfg, "", "/srv/x") == "/srv/x"
    assert locations.users_of(cfg, "s3") == ["Docs"]
    assert locations.users_of(cfg, "nas") == ["Carpetas personales"]
    with pytest.raises(locations.LocationError, match="Docs"):
        locations.remove(cfg, "s3")
    assert locations.local_exists("s3", "docs") is None
    stored = {**nas, "password": "viejo", "username": "u", "port": 445, "encrypt": True}
    form = {"label": "NAS 2", "server": "srv2", "share": "files", "path": "", "username": "u", "password": "",
            "port": "445", "encrypt": "on"}
    edited = locations.from_form(form, stored)
    assert edited["password"] == "viejo" and edited["name"] == "nas" and edited["server"] == "srv2"
    assert locations.from_form({**form, "password": "nuevo"}, stored)["password"] == "nuevo"

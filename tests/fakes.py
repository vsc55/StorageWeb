"""Clientes falsos de S3, SMB, SFTP, FTP, WebDAV y Azure para probar los backends sin servidores.

Imitan solo lo que usan ``core/backends``: las respuestas tienen la forma de las reales y los
errores llevan ``response["Error"]["Code"]`` como los de botocore.
"""
from __future__ import annotations

import ftplib
import io
import os
from datetime import datetime, timezone
from pathlib import Path


class ClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    """Un único bucket en memoria. ``page_size`` pequeño obliga a paginar como en S3 de verdad."""

    def __init__(self, bucket: str = "bucket", page_size: int = 2):
        self.bucket, self.page_size = bucket, page_size
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self.fail: str | None = None  # código de error para todas las llamadas (credenciales, etc.)
        self.calls: list[str] = []

    def _check(self, name: str, bucket: str) -> None:
        self.calls.append(name)
        if self.fail:
            raise ClientError(self.fail)
        if bucket != self.bucket:
            raise ClientError("NoSuchBucket")

    def put(self, key: str, data: bytes = b"") -> None:
        self.objects[key] = (data, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    # --------------------------------------------------------------- API de boto3
    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=1000, ContinuationToken=None):
        self._check("list_objects_v2", Bucket)
        items: list[tuple[str, str]] = []  # (clave o prefijo común, tipo)
        seen_prefixes = set()
        for key in sorted(self.objects):
            if not key.startswith(Prefix):
                continue
            rest = key[len(Prefix):]
            if Delimiter and Delimiter in rest:
                common = Prefix + rest.split(Delimiter)[0] + Delimiter
                if common not in seen_prefixes:
                    seen_prefixes.add(common)
                    items.append((common, "prefix"))
                continue
            items.append((key, "key"))
        start = int(ContinuationToken or 0)
        size = min(MaxKeys, self.page_size)
        page, more = items[start:start + size], start + size < len(items)
        result = {"KeyCount": len(page), "IsTruncated": more,
                  "Contents": [{"Key": k, "Size": len(self.objects[k][0]), "LastModified": self.objects[k][1]}
                               for k, kind in page if kind == "key"],
                  "CommonPrefixes": [{"Prefix": k} for k, kind in page if kind == "prefix"]}
        if more:
            result["NextContinuationToken"] = str(start + size)
        return result

    def head_object(self, Bucket, Key):
        self._check("head_object", Bucket)
        if Key not in self.objects:
            raise ClientError("404")
        data, mtime = self.objects[Key]
        return {"ContentLength": len(data), "LastModified": mtime}

    def get_object(self, Bucket, Key, Range=None):
        self._check("get_object", Bucket)
        if Key not in self.objects:
            raise ClientError("NoSuchKey")
        data = self.objects[Key][0]
        if Range:
            start = int(Range.removeprefix("bytes=").split("-")[0])
            data = data[start:]
        return {"Body": io.BytesIO(data)}

    def put_object(self, Bucket, Key, Body=b""):
        self._check("put_object", Bucket)
        self.put(Key, Body)

    def copy_object(self, Bucket, Key, CopySource):
        self._check("copy_object", Bucket)
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, Bucket, Key):
        self._check("delete_object", Bucket)
        self.objects.pop(Key, None)

    def delete_objects(self, Bucket, Delete):
        self._check("delete_objects", Bucket)
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)

    def upload_file(self, Filename, Bucket, Key):
        self._check("upload_file", Bucket)
        self.put(Key, Path(Filename).read_bytes())


class FakeSMB:
    """``smbclient`` sobre una carpeta local: ``\\\\servidor\\recurso\\a\\b`` → ``root/servidor/recurso/a/b``."""

    def __init__(self, root: Path):
        self.root = root

    def _p(self, unc: str) -> Path:
        assert unc.startswith("\\\\"), unc
        return self.root.joinpath(*[p for p in unc[2:].split("\\") if p])

    def stat(self, unc):
        return os.stat(self._p(unc))

    def scandir(self, unc):
        return os.scandir(self._p(unc))

    def open_file(self, unc, mode="rb"):
        return open(self._p(unc), mode)

    def mkdir(self, unc):
        self._p(unc).mkdir()

    def makedirs(self, unc, exist_ok=False):
        self._p(unc).mkdir(parents=True, exist_ok=exist_ok)

    def rename(self, src, dst):
        os.rename(self._p(src), self._p(dst))

    def remove(self, unc):
        os.remove(self._p(unc))

    def rmdir(self, unc):
        os.rmdir(self._p(unc))


# --------------------------------------------------------------------------- SFTP (paramiko)

class FakeSFTP:
    """El subconjunto de ``paramiko.SFTPClient`` que usa el backend, sobre una carpeta local."""

    def __init__(self, root: Path):
        self.root = root

    def _p(self, path: str) -> Path:
        return self.root.joinpath(*[p for p in path.split("/") if p not in ("", ".")])

    def stat(self, path):
        return os.stat(self._p(path))

    def listdir_attr(self, path):
        items = []
        for entry in os.scandir(self._p(path)):
            st = entry.stat()
            item = type("Attr", (), {})()
            item.filename, item.st_mode, item.st_size, item.st_mtime = entry.name, st.st_mode, st.st_size, st.st_mtime
            items.append(item)
        return items

    def open(self, path, mode="rb"):
        return open(self._p(path), mode)

    def mkdir(self, path):
        self._p(path).mkdir()

    def rename(self, src, dst):
        os.rename(self._p(src), self._p(dst))

    def remove(self, path):
        os.remove(self._p(path))

    def rmdir(self, path):
        os.rmdir(self._p(path))

    def put(self, local, path):
        self._p(path).write_bytes(Path(local).read_bytes())


class FakeSFTPSession:
    def __init__(self, root: Path):
        self.client = FakeSFTP(root)

    def sftp(self):
        return self.client


# --------------------------------------------------------------------------- FTP (ftplib)

class FakeFTP:
    """El subconjunto de ``ftplib.FTP`` que usa el backend. ``mlsd=False`` imita un servidor sin MLSD."""

    def __init__(self, root: Path, mlsd: bool = True):
        self.root, self.has_mlsd = root, mlsd
        self.cwd_path = "/"

    def __call__(self, *args, **kwargs):  # se usa como «clase»: fake(timeout=…) da una conexión nueva
        return FakeFTP(self.root, self.has_mlsd)

    def _p(self, path: str) -> Path:
        full = path if path.startswith("/") else self.cwd_path.rstrip("/") + "/" + path
        return self.root.joinpath(*[p for p in full.split("/") if p not in ("", ".")])

    def _need(self, path: str) -> Path:
        p = self._p(path)
        if not p.exists():
            raise ftplib.error_perm(f"550 {path}: no existe")
        return p

    def connect(self, host, port):
        pass

    def login(self, user, passwd):
        if user == "malo":
            raise ftplib.error_perm("530 Login incorrect")

    def prot_p(self):
        pass

    def set_pasv(self, value):
        pass

    def pwd(self):
        return self.cwd_path

    def cwd(self, path):
        p = self._need(path)
        if not p.is_dir():
            raise ftplib.error_perm(f"550 {path}: no es una carpeta")
        self.cwd_path = "/" + "/".join(p.relative_to(self.root).parts)

    def mlsd(self, path="", facts=()):
        if not self.has_mlsd:
            raise ftplib.error_perm("500 MLSD no reconocido")
        p = self._need(path)
        items = [(".", {"type": "cdir"})]
        for entry in os.scandir(p):
            st = entry.stat()
            modify = datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y%m%d%H%M%S")
            items.append((entry.name, {"type": "dir" if entry.is_dir() else "file", "size": str(st.st_size),
                                       "modify": modify}))
        return iter(items)

    def nlst(self, path=""):
        return [f"{path.rstrip('/')}/{name}" for name in os.listdir(self._need(path))]

    def voidcmd(self, cmd):
        if cmd.startswith("MDTM "):
            st = self._need(cmd[5:]).stat()
            return "213 " + datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y%m%d%H%M%S")
        return "200 OK"

    def size(self, path):
        return self._need(path).stat().st_size

    def mkd(self, path):
        p = self._p(path)
        if p.exists() or not p.parent.is_dir():
            raise ftplib.error_perm(f"550 {path}: no se puede crear")
        p.mkdir()
        return path

    def rmd(self, path):
        os.rmdir(self._need(path))

    def delete(self, path):
        os.remove(self._need(path))

    def rename(self, src, dst):
        os.rename(self._need(src), self._p(dst))

    def storbinary(self, cmd, fp, blocksize=8192):
        self._p(cmd[5:]).write_bytes(fp.read())

    def transfercmd(self, cmd, rest=None):
        fh = open(self._need(cmd[5:]), "rb")
        fh.seek(rest or 0)
        sock = type("Sock", (), {})()
        sock.makefile = lambda mode: fh
        sock.close = fh.close
        return sock

    def quit(self):
        pass

    def close(self):
        pass


# --------------------------------------------------------------------------- WebDAV

def fake_webdav_client(root: Path, location: dict | None = None):
    """``WebDAVClient`` con un servidor WebDAV en memoria sobre una carpeta local (respuestas en XML de verdad)."""
    import email.utils
    import shutil
    import urllib.parse
    from xml.sax.saxutils import escape

    from storageweb.core.backends.webdav import Response, WebDAVClient

    class Client(WebDAVClient):
        requests: list = []

        def _local(self, url: str) -> Path:
            path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
            base = urllib.parse.unquote(urllib.parse.urlsplit(self.base_url).path)
            assert path.startswith(base.rstrip("/")), (path, base)
            target = root.joinpath(*[p for p in path[len(base.rstrip("/")):].split("/") if p])
            # Como un servidor de verdad, nunca sale de su raíz: en Windows un trozo como «C:Windows» cambia de
            # unidad al unirlo (si los temporales de los tests están en otra), y eso sería un fallo del fake, no
            # de StorageWeb. Lo de fuera no existe (404)
            try:
                target.relative_to(root)
            except ValueError:
                return root / ".fake-outside-root"
            return target

        def _href(self, p: Path) -> str:
            rel = "/".join(p.relative_to(root).parts)
            href = urllib.parse.urlsplit(self.base_url).path + urllib.parse.quote(rel)
            return href + ("/" if p.is_dir() and rel else "")

        def _prop(self, p: Path) -> str:
            st = p.stat()
            kind = "<d:collection/>" if p.is_dir() else ""
            length = "" if p.is_dir() else f"<d:getcontentlength>{st.st_size}</d:getcontentlength>"
            date = email.utils.formatdate(st.st_mtime, usegmt=True)
            return (f"<d:response><d:href>{escape(self._href(p))}</d:href><d:propstat><d:prop>"
                    f"<d:resourcetype>{kind}</d:resourcetype>{length}<d:getlastmodified>{date}</d:getlastmodified>"
                    "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")

        def send(self, method, url, headers, body=None, stream=False):
            self.requests.append((method, url))
            p = self._local(url)
            if method == "PROPFIND":
                if not p.exists():
                    return Response(404, {}, b"")
                items = [p] + (sorted(p.iterdir()) if p.is_dir() and headers.get("Depth") == "1" else [])
                xml = '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">' + "".join(map(self._prop, items))
                return Response(207, {}, (xml + "</d:multistatus>").encode())
            if method == "GET":
                if not p.is_file():
                    return Response(404, {}, b"")
                start = int(headers["Range"][6:].split("-")[0]) if "Range" in headers else 0
                return Response(206 if start else 200, {}, io.BytesIO(p.read_bytes()[start:]))
            if method == "PUT":
                p.write_bytes(body.read() if hasattr(body, "read") else body)
                return Response(201, {}, b"")
            if method == "MKCOL":
                if p.exists():
                    return Response(405, {}, b"")
                if not p.parent.is_dir():
                    return Response(409, {}, b"")
                p.mkdir()
                return Response(201, {}, b"")
            if method == "MOVE":
                dest = self._local(headers["Destination"])
                if dest.exists() and headers.get("Overwrite") == "F":
                    return Response(412, {}, b"")
                os.rename(p, dest)
                return Response(201, {}, b"")
            if method == "DELETE":
                if not p.exists():
                    return Response(404, {}, b"")
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                return Response(204, {}, b"")
            return Response(405, {}, b"")

    return Client(location or {"url": "https://dav.example/remote.php/dav/files/ana/"})


# --------------------------------------------------------------------------- Azure Blob

class FakeAzureError(Exception):
    def __init__(self, status_code: int, error_code: str = ""):
        super().__init__(error_code or str(status_code))
        self.status_code, self.error_code = status_code, error_code


class FakeAzureContainer:
    """El subconjunto de ``azure.storage.blob.ContainerClient`` que usa el backend, en memoria."""

    def __init__(self):
        self.blobs: dict[str, tuple[bytes, datetime]] = {}
        self.fail: FakeAzureError | None = None

    def _check(self):
        if self.fail:
            raise self.fail

    def _props(self, name):
        data, modified = self.blobs[name]
        props = type("BlobProperties", (), {})()
        props.name, props.size, props.last_modified = name, len(data), modified
        return props

    def get_container_properties(self):
        self._check()
        return {}

    def get_blob_client(self, name):
        container = self

        class Blob:
            def get_blob_properties(self):
                container._check()
                if name not in container.blobs:
                    raise FakeAzureError(404, "BlobNotFound")
                return container._props(name)
        return Blob()

    def list_blobs(self, name_starts_with=""):
        self._check()
        return iter([self._props(n) for n in sorted(self.blobs) if n.startswith(name_starts_with)])

    def walk_blobs(self, name_starts_with="", delimiter="/"):
        self._check()
        seen, items = set(), []
        for name in sorted(self.blobs):
            if not name.startswith(name_starts_with):
                continue
            rest = name[len(name_starts_with):]
            if delimiter in rest:
                prefix = name_starts_with + rest.split(delimiter)[0] + delimiter
                if prefix not in seen:
                    seen.add(prefix)
                    item = type("BlobPrefix", (), {})()
                    item.name = prefix
                    items.append(item)
                continue
            items.append(self._props(name))
        return iter(items)

    def download_blob(self, name, offset=0):
        self._check()
        if name not in self.blobs:
            raise FakeAzureError(404, "BlobNotFound")
        data = self.blobs[name][0][offset:]
        down = type("Downloader", (), {})()
        down.size = len(data)
        down.chunks = lambda: iter([data[i:i + 7] for i in range(0, len(data), 7)])
        return down

    def upload_blob(self, name, data, overwrite=False, length=None):
        self._check()
        if name in self.blobs and not overwrite:
            raise FakeAzureError(409, "BlobAlreadyExists")
        payload = data if isinstance(data, bytes) else data.read()
        self.blobs[name] = (payload, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))

    def delete_blob(self, name):
        self._check()
        if name not in self.blobs:
            raise FakeAzureError(404, "BlobNotFound")
        del self.blobs[name]

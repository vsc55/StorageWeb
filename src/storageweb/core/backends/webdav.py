"""Almacenamiento en un servidor WebDAV: Nextcloud, ownCloud, SharePoint, NAS (Synology, QNAP…).

Sin dependencias: HTTP con ``urllib``. ``PROPFIND`` para consultar y listar, ``GET`` con ``Range`` para
leer desde cualquier posición, ``PUT``, ``MKCOL``, ``MOVE`` y ``DELETE`` para el resto. Autenticación
básica sobre HTTPS (en Nextcloud, mejor con una contraseña de aplicación).

Dirección de ejemplo en Nextcloud: ``https://nube.empresa.es/remote.php/dav/files/<usuario>/``.
"""
from __future__ import annotations

import base64
import io
import posixpath
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

from ...i18n import _, _l
from ...settings.location_types import LocationSchema, Option
from .base import (BackendError, Entry, RangedReader, RemoteBackend, certificate_error, clean_rel, join_rel,
                   name_of)
from ...tls import client_context

TIMEOUT = 30         # sin la opción «timeout» de la ubicación (la de serie)
DAV = "{DAV:}"
PROPFIND_BODY = (b'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop>'
                 b"<d:resourcetype/><d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>")


class WebDAVError(Exception):
    def __init__(self, status: int, reason: str = ""):
        super().__init__(f"HTTP {status} {reason}".strip())
        self.status = status


def _error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    status = getattr(exc, "status", None)
    if status in (401, 403):
        return BackendError(_("The WebDAV server denied the access: check the user, the password and the "
                              "address."))
    if status == 507:
        return BackendError(_("The WebDAV server has no space left."))
    return BackendError(_("WebDAV error: %(error)s", error=exc))


class Response:
    def __init__(self, status: int, headers: dict, body):
        self.status, self.headers, self.body = status, headers, body  # body: bytes o fichero para leer

    def read(self, n: int = -1) -> bytes:
        return self.body.read(n) if hasattr(self.body, "read") else self.body

    def close(self) -> None:
        if hasattr(self.body, "close"):
            self.body.close()


class WebDAVClient:
    """Peticiones HTTP a un servidor WebDAV. Los tests sustituyen :meth:`send`."""

    def __init__(self, location: dict):
        self.base_url = location["url"].rstrip("/") + "/"
        self.timeout = int(location.get("timeout") or TIMEOUT)
        self.headers = {"User-Agent": "StorageWeb"}
        if location.get("username"):
            token = f"{location['username']}:{location.get('password') or ''}".encode()
            self.headers["Authorization"] = "Basic " + base64.b64encode(token).decode()
        self.context = client_context(location.get("verify_tls", True))

    def url(self, path: str) -> str:
        """URL de una ruta relativa a la dirección configurada (cada parte, codificada; conserva la «/» final)."""
        quoted = "/".join(urllib.parse.quote(p) for p in path.split("/") if p)
        return self.base_url + quoted + ("/" if quoted and path.endswith("/") else "")

    def send(self, method: str, url: str, headers: dict, body=None, stream: bool = False) -> Response:
        req = urllib.request.Request(url, data=body, method=method, headers={**self.headers, **headers})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout, context=self.context)  # noqa: S310 (URL configurada)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            exc.close()
            return Response(exc.code, dict(exc.headers or {}), data)
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                exc = reason
                raise certificate_error(exc) from exc
            raise BackendError(_("Cannot connect to the WebDAV server: %(error)s", error=reason)) from exc
        if stream:
            return Response(resp.status, dict(resp.headers), resp)
        with resp:
            return Response(resp.status, dict(resp.headers), resp.read())

    def request(self, method: str, path: str, headers: dict | None = None, body=None, stream: bool = False,
                ok=(200, 201, 204, 207)) -> Response:
        resp = self.send(method, self.url(path), headers or {}, body, stream)
        if resp.status not in ok:
            resp.close()
            raise WebDAVError(resp.status)
        return resp


def _parse_multistatus(xml: bytes) -> list[tuple[str, Entry]]:
    """``[(ruta del href sin codificar, Entry)]`` de una respuesta ``207 Multi-Status``."""
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:  # sin entidades: nada de «billion laughs» ni XXE
        raise ET.ParseError("DOCTYPE no permitido en la respuesta WebDAV")
    root = ET.fromstring(xml)
    found = []
    for response in root.iter(f"{DAV}response"):
        href = urllib.parse.unquote(urllib.parse.urlsplit(response.findtext(f"{DAV}href") or "").path)
        is_dir, size, mtime = False, 0, 0.0
        for propstat in response.iter(f"{DAV}propstat"):
            if " 200" not in (propstat.findtext(f"{DAV}status") or " 200"):
                continue
            prop = propstat.find(f"{DAV}prop")
            if prop is None:
                continue
            kind = prop.find(f"{DAV}resourcetype")
            if kind is not None and kind.find(f"{DAV}collection") is not None:
                is_dir = True
            length = prop.findtext(f"{DAV}getcontentlength")
            if length and length.strip().isdigit():
                size = int(length)
            modified = prop.findtext(f"{DAV}getlastmodified")
            if modified:
                try:
                    mtime = parsedate_to_datetime(modified).timestamp()
                except (TypeError, ValueError):
                    pass
        name = posixpath.basename(href.rstrip("/"))
        found.append((href.rstrip("/"), Entry(name, is_dir, 0 if is_dir else size, mtime)))
    return found


class WebDAVBackend(RemoteBackend):
    kind = "webdav"
    schema = LocationSchema(
        kind="webdav",
        windows_option=True,
        label=_l("WebDAV (Nextcloud, ownCloud, SharePoint, NAS…)"),
        short_label="WebDAV",
        doc="Servidor WebDAV (Nextcloud, ownCloud, SharePoint, NAS). Sin dependencias.",
        place_title=_l("Server"),
        label_placeholder=_l("Company cloud"),
        name_placeholder="nube",
        credentials_help=_l("In Nextcloud and ownCloud, better an app password (Settings → Security)."),
        options=(
            Option("url", _l("Address"), "Dirección WebDAV. Nextcloud: `https://servidor/remote.php/dav/files/<usuario>/`.",
                   kind="url", required=True, placeholder="https://cloud.example.com/remote.php/dav/files/user/",
                   help=_l("Nextcloud and ownCloud: https://server/remote.php/dav/files/USER/")),
            Option("path", _l("Folder"), "Carpeta dentro de esa dirección donde va todo (vacía = su raíz).",
                   kind="path", placeholder="storageweb",
                   help=_l("Folder inside that address where everything goes (empty = its root).")),
            Option("verify_tls", _l("Check the certificate"),
                   "Comprobar el certificado TLS del servidor. Desactívalo solo con certificados propios.",
                   kind="bool", default=True,
                   help=_l("Disable it only for servers with their own certificate (many NAS).")),
            Option("timeout", _l("Wait for the server (seconds)"),
                   "Segundos que se espera al servidor (conectar y cada respuesta) antes de dar la operación por fallida (de 1 a 600). Súbelo para un servidor lento o lejano.", kind="seconds", default=30,
                   help=_l("How long to wait for the server before giving up. Raise it for a slow or distant server.")),
            Option("username", _l("User"), "Usuario.", section="credentials"),
            Option("password", _l("Password"), "Contraseña o contraseña de aplicación (secreto).", kind="secret",
                   section="credentials"),
        ),
    )

    def __init__(self, client: WebDAVClient, base: str, staging: Path):
        super().__init__(staging)
        self.client = client
        self.base = clean_rel(base)

    @classmethod
    def connect(cls, location: dict):
        return WebDAVClient(location)

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> WebDAVBackend:
        return cls(client, join_rel(location.get("path", ""), base), staging)

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        return (location["url"].rstrip("/") + "/" + join_rel(location.get("path", ""), path)).rstrip("/")

    def describe(self) -> str:
        return self.client.url(self.base)

    def _p(self, rel: str) -> str:
        return join_rel(self.base, self._clean(rel))

    def _propfind(self, rel: str, depth: str) -> list[tuple[str, Entry]] | None:
        resp = self.client.send("PROPFIND", self.client.url(self._p(rel)),
                                {"Depth": depth, "Content-Type": "application/xml; charset=utf-8"}, PROPFIND_BODY)
        if resp.status == 404:
            return None
        if resp.status != 207:
            raise WebDAVError(resp.status)
        return _parse_multistatus(resp.read())

    def stat(self, rel: str) -> Entry | None:
        try:
            found = self._propfind(rel, "0")
        except (WebDAVError, ET.ParseError) as exc:
            raise _error(exc) from exc
        if not found:
            return None
        entry = found[0][1]
        return Entry(name_of(clean_rel(rel)), entry.is_dir, entry.size, entry.mtime)

    def listdir(self, rel: str) -> list[Entry]:
        try:
            found = self._propfind(rel, "1")
        except (WebDAVError, ET.ParseError) as exc:
            raise _error(exc) from exc
        if found is None:
            raise BackendError(_("WebDAV error: %(error)s", error="404"))
        own = urllib.parse.unquote(urllib.parse.urlsplit(self.client.url(self._p(rel))).path).rstrip("/")
        return [entry for href, entry in found if href != own and entry.name]

    def open(self, rel: str):
        entry = self._file_entry(rel)
        path = self._p(rel)

        def fetch(pos: int):
            try:
                resp = self.client.request("GET", path, {"Range": f"bytes={pos}-"} if pos else {}, stream=True,
                                           ok=(200, 206))
            except WebDAVError as exc:
                raise _error(exc) from exc
            if pos and resp.status == 200:  # el servidor no admite Range: se descarta lo anterior
                resp.read(pos)
            return resp
        return io.BufferedReader(RangedReader(fetch, entry.size), 256 * 1024), entry.size, entry.mtime

    def mkdir(self, rel: str) -> None:
        if self.exists(rel):
            raise FileExistsError(rel)
        try:
            self.client.request("MKCOL", self._p(rel), ok=(200, 201))
        except WebDAVError as exc:
            raise _error(exc) from exc

    def _move(self, rel: str, new_rel: str, entry: Entry) -> None:
        suffix = "/" if entry.is_dir else ""
        try:
            self.client.request("MOVE", self._p(rel) + suffix,
                                {"Destination": self.client.url(self._p(new_rel) + suffix), "Overwrite": "F"},
                                ok=(201, 204))
        except WebDAVError as exc:
            if exc.status == 412:
                raise FileExistsError(name_of(new_rel)) from exc
            raise _error(exc) from exc

    def delete(self, rel: str) -> None:
        entry = self._existing(rel)
        try:  # una carpeta se borra con todo su contenido
            self.client.request("DELETE", self._p(rel) + ("/" if entry.is_dir else ""), ok=(200, 204))
        except WebDAVError as exc:
            raise _error(exc) from exc

    def store(self, local: Path, rel: str) -> None:
        size = local.stat().st_size
        try:
            with open(local, "rb") as src:
                self.client.request("PUT", self._p(rel), {"Content-Length": str(size),
                                                          "Content-Type": "application/octet-stream"}, src,
                                    ok=(200, 201, 204))
        except WebDAVError as exc:
            raise _error(exc) from exc
        local.unlink(missing_ok=True)

    def ensure_root(self, home: bool = False) -> None:
        built = ""
        for part in self.base.split("/") if self.base else []:
            built = join_rel(built, part)
            try:
                found = self.client.send("PROPFIND", self.client.url(built), {"Depth": "0"}, PROPFIND_BODY)
                if found.status == 404:
                    self.client.request("MKCOL", built, ok=(200, 201, 405))
                elif found.status != 207:
                    raise WebDAVError(found.status)
            except WebDAVError as exc:
                raise _error(exc) from exc

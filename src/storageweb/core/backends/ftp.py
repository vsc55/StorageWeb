"""Almacenamiento en un servidor FTP o FTPS (FTP con TLS): NAS, hostings, equipos antiguos.

Usa ``ftplib`` (biblioteca estándar, sin dependencias). FTP no permite varias operaciones a la vez por
conexión, así que cada operación abre la suya (modo pasivo). Para listar usa ``MLSD`` y, si el servidor
no lo tiene, ``NLST`` preguntando por cada nombre. Las descargas usan ``REST`` para empezar donde haga
falta (descargas reanudadas, vídeo).

Con ``tls`` (recomendado) la sesión y los datos van cifrados (FTPS explícito). ``verify_tls``
comprueba el certificado; desactívalo solo con certificados propios de un NAS.
"""
from __future__ import annotations

import ftplib
import io
import posixpath
import ssl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ...i18n import _, _l
from ...settings.location_types import LocationSchema, Option
from .base import (BackendError, Entry, RangedReader, RemoteBackend, certificate_error, clean_rel, join_rel,
                   name_of)

TIMEOUT = 30


def _error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    text = str(exc)
    if isinstance(exc, ssl.SSLCertVerificationError):
        return certificate_error(exc)
    if isinstance(exc, ftplib.error_perm) and text[:3] in ("530", "532"):
        return BackendError(_("The FTP server rejected the user or the password."))
    if isinstance(exc, ftplib.error_perm) and text[:3] == "550":
        return BackendError(_("The FTP server denied the access to the folder: %(error)s", error=text))
    return BackendError(_("FTP error: %(error)s", error=text or exc.__class__.__name__))


def _mtime(value: str) -> float:
    """``YYYYMMDDHHMMSS[.sss]`` (MLSD/MDTM, en UTC) → marca de tiempo."""
    try:
        return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


class FTPConnector:
    """Abre conexiones a una ubicación. ``ftp_class`` se puede sustituir (tests)."""

    def __init__(self, location: dict, ftp_class=None, tls_class=None):
        self.location = location
        self.ftp_class = ftp_class or ftplib.FTP
        self.tls_class = tls_class or ftplib.FTP_TLS

    def open(self):
        loc = self.location
        if loc.get("tls"):
            context = ssl.create_default_context()
            if not loc.get("verify_tls", True):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            ftp = self.tls_class(context=context, timeout=TIMEOUT)
        else:
            ftp = self.ftp_class(timeout=TIMEOUT)
        ftp.connect(loc["host"], int(loc.get("port") or 21))
        ftp.login(loc.get("username") or "anonymous", loc.get("password") or "")
        if loc.get("tls"):
            ftp.prot_p()
        ftp.set_pasv(True)
        return ftp

    @contextmanager
    def session(self):
        try:
            ftp = self.open()
        except BackendError:
            raise
        except (OSError, EOFError, ftplib.Error) as exc:
            raise _error(exc) from exc
        try:
            yield ftp
        except (EOFError, ftplib.Error, ConnectionError, TimeoutError, ssl.SSLError) as exc:
            raise _error(exc) from exc
        finally:
            try:
                ftp.quit()
            except (OSError, EOFError, ftplib.Error):
                ftp.close()


def _is_dir(ftp, path: str) -> bool:
    """Si ``path`` es una carpeta (CWD), sin cambiar la carpeta actual de la sesión."""
    here = ftp.pwd()
    try:
        ftp.cwd(path)
    except ftplib.error_perm:
        return False
    ftp.cwd(here)
    return True


class _Download:
    """Lectura de un ``RETR`` (desde ``rest``) con su propia conexión, que se cierra al terminar."""

    def __init__(self, ftp, sock):
        self.ftp, self.sock = ftp, sock
        self.stream = sock.makefile("rb")

    def read(self, n: int = -1) -> bytes:
        return self.stream.read(n)

    def close(self) -> None:
        for closer in (self.stream.close, self.sock.close, self.ftp.close):
            try:
                closer()
            except (OSError, EOFError, ftplib.Error):
                pass


class FTPBackend(RemoteBackend):
    kind = "ftp"
    schema = LocationSchema(
        kind="ftp",
        label=_l("FTP / FTPS"),
        short_label="FTP",
        doc="Servidor FTP o FTPS (FTP con TLS). Sin dependencias.",
        place_title=_l("Server"),
        label_placeholder=_l("Files server"),
        name_placeholder="ftp",
        credentials_help=_l("Empty user = anonymous access."),
        options=(
            Option("host", _l("Server"), "Nombre o IP del servidor.", required=True, placeholder="ftp.example.com"),
            Option("port", _l("Port"), "Puerto (`21`).", kind="port", default=21),
            Option("path", _l("Folder"),
                   "Carpeta del servidor donde va todo: absoluta (`/datos`) o relativa a la del usuario.",
                   kind="server_path", placeholder="/storageweb",
                   help=_l("Absolute (/srv/files) or relative to the home folder of the user (empty = that folder).")),
            Option("tls", _l("Encrypt with TLS (FTPS)"), "Usar FTPS explícito (`AUTH TLS`): sesión y datos cifrados.",
                   kind="bool", default=True,
                   help=_l("Recommended. Without it the password and the files travel in clear text.")),
            Option("verify_tls", _l("Check the certificate"),
                   "Comprobar el certificado TLS del servidor. Desactívalo solo con certificados propios.",
                   kind="bool", default=True,
                   help=_l("Disable it only for servers with their own certificate (many NAS).")),
            Option("username", _l("User"), "Usuario (vacío = anónimo).", section="credentials"),
            Option("password", _l("Password"), "Contraseña (secreto).", kind="secret", section="credentials"),
        ),
    )

    def __init__(self, client: FTPConnector, base: str, staging: Path, label: str = ""):
        super().__init__(staging)
        self.client, self.label = client, label
        self.absolute = base.startswith("/")
        self.base = clean_rel(base)

    @classmethod
    def connect(cls, location: dict):
        return FTPConnector(location)

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> FTPBackend:
        root = location.get("path", "")
        return cls(client, ("/" if root.startswith("/") else "") + join_rel(root, base), staging,
                   cls.address(location))

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        root = location.get("path", "")
        port = int(location.get("port") or 21)
        scheme = "ftps" if location.get("tls") else "ftp"
        where = location["host"] + (f":{port}" if port != 21 else "")
        user = f"{location['username']}@" if location.get("username") else ""
        home = "" if root.startswith("/") else "~/"  # absoluta o relativa a la carpeta del usuario
        return f"{scheme}://{user}{where}/{home}{join_rel(root, path)}".rstrip("/")

    def describe(self) -> str:
        return self.label

    def _p(self, rel: str) -> str:
        joined = join_rel(self.base, clean_rel(rel))
        return ("/" + joined) if self.absolute else joined

    def _dir(self, rel: str) -> str:
        return self._p(rel) or ("/" if self.absolute else ".")

    # ------------------------------------------------------------------ listados
    def _entries(self, ftp, rel: str) -> list[Entry]:
        path = self._dir(rel)
        try:
            items = list(ftp.mlsd(path, facts=["type", "size", "modify"]))
        except ftplib.error_perm as exc:
            if str(exc)[:3] not in ("500", "501", "502", "504"):  # no es «MLSD no existe»
                raise
            return self._entries_nlst(ftp, path)
        entries = []
        for name, facts in items:
            kind = facts.get("type", "").lower()
            if kind in ("cdir", "pdir") or name in (".", ".."):
                continue
            is_dir = kind == "dir"
            entries.append(Entry(posixpath.basename(name.rstrip("/")), is_dir,
                                 0 if is_dir else int(facts.get("size") or 0), _mtime(facts.get("modify", ""))))
        return entries

    def _entries_nlst(self, ftp, path: str) -> list[Entry]:
        """Servidores sin MLSD: nombres con NLST y, por cada uno, si es carpeta (CWD) o su tamaño (SIZE)."""
        entries = []
        for name in ftp.nlst(path):
            base = posixpath.basename(name.rstrip("/"))
            if base in (".", ".."):
                continue
            full = posixpath.join(path, base)
            if _is_dir(ftp, full):
                entries.append(Entry(base, True))
                continue
            size = 0
            mtime = 0.0
            try:
                ftp.voidcmd("TYPE I")
                size = int(ftp.size(full) or 0)
                mtime = _mtime(ftp.voidcmd(f"MDTM {full}").split()[-1])
            except ftplib.error_perm:
                pass
            entries.append(Entry(base, False, size, mtime))
        return entries

    def _stat(self, ftp, rel: str) -> Entry | None:
        rel = clean_rel(rel)
        if not rel:
            return Entry("", True) if _is_dir(ftp, self._dir("")) else None
        parent, name = posixpath.dirname(rel), name_of(rel)
        try:
            found = self._entries(ftp, parent)
        except ftplib.error_perm:
            return None  # la carpeta de arriba no existe
        return next((e for e in found if e.name == name), None)

    # ------------------------------------------------------------------ interfaz
    def stat(self, rel: str) -> Entry | None:
        with self.client.session() as ftp:
            return self._stat(ftp, rel)

    def listdir(self, rel: str) -> list[Entry]:
        with self.client.session() as ftp:
            return self._entries(ftp, rel)

    def open(self, rel: str):
        entry = self.stat(rel)
        if entry is None or entry.is_dir:
            raise FileNotFoundError(rel)
        path = self._p(rel)

        def fetch(pos: int):
            try:
                ftp = self.client.open()
                ftp.voidcmd("TYPE I")
                return _Download(ftp, ftp.transfercmd(f"RETR {path}", rest=pos or None))
            except (OSError, EOFError, ftplib.Error) as exc:
                raise _error(exc) from exc
        return io.BufferedReader(RangedReader(fetch, entry.size), 256 * 1024), entry.size, entry.mtime

    def mkdir(self, rel: str) -> None:
        with self.client.session() as ftp:
            if self._stat(ftp, rel) is not None:
                raise FileExistsError(rel)
            ftp.mkd(self._p(rel))

    def _move(self, rel: str, new_rel: str, entry: Entry) -> None:
        with self.client.session() as ftp:
            ftp.rename(self._p(rel), self._p(new_rel))

    def _remove_tree(self, ftp, rel: str) -> None:
        for item in self._entries(ftp, rel):
            child = join_rel(rel, item.name)
            if item.is_dir:
                self._remove_tree(ftp, child)
            else:
                ftp.delete(self._p(child))
        ftp.rmd(self._p(rel))

    def delete(self, rel: str) -> None:
        with self.client.session() as ftp:
            entry = self._stat(ftp, rel)
            if entry is None:
                raise FileNotFoundError(rel)
            if entry.is_dir:
                self._remove_tree(ftp, clean_rel(rel))
            else:
                ftp.delete(self._p(rel))

    def store(self, local: Path, rel: str) -> None:
        with self.client.session() as ftp, open(local, "rb") as src:
            ftp.storbinary(f"STOR {self._p(rel)}", src, blocksize=256 * 1024)
        local.unlink(missing_ok=True)

    def root_exists(self) -> bool:
        return self.stat("") is not None

    def ensure_root(self, home: bool = False) -> None:
        with self.client.session() as ftp:
            built = ""
            for part in self.base.split("/") if self.base else []:
                built = join_rel(built, part)
                path = ("/" + built) if self.absolute else built
                if not _is_dir(ftp, path):
                    ftp.mkd(path)

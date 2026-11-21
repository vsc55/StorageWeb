"""Almacenamiento en un servidor SFTP (SSH): Linux, NAS, hostings.

Usa ``paramiko`` (extra ``[sftp]``). Una conexión SSH por ubicación y proceso; cada hilo abre su propio
canal SFTP sobre ella (paramiko no admite operaciones simultáneas en un mismo canal). Si la conexión
se cae, se reabre en la siguiente operación.

La clave del servidor se comprueba con ``host_key`` (la línea de ``ssh-keyscan`` o la huella
``SHA256:…``). Sin ella se acepta cualquiera: cómodo para probar, pero expuesto a suplantaciones.
"""
from __future__ import annotations

import base64
import hashlib
import io
import stat as statmod
import threading
from pathlib import Path

from ...i18n import _, _l
from ...settings.location_types import LocationSchema, Option
from .base import BackendError, Entry, RemoteBackend, clean_rel, join_rel, name_of

TIMEOUT = 20         # sin la opción «timeout» de la ubicación (la de serie)


def _error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    if isinstance(exc, PermissionError):
        return BackendError(_("The SFTP server denied the access: check the user, the key and the folder "
                              "permissions."))
    if any(cls.__name__ == "AuthenticationException" for cls in type(exc).__mro__):
        return BackendError(_("The SFTP server rejected the user, the password or the key."))
    return BackendError(_("SFTP error: %(error)s", error=exc))


def host_key_matches(expected: str, key_type: str, key_bytes: bytes) -> bool:
    """``expected`` es «tipo base64 [comentario]» (ssh-keyscan) o «SHA256:huella» (ssh-keygen -l)."""
    expected = expected.strip()
    if expected.startswith("SHA256:"):
        digest = base64.b64encode(hashlib.sha256(key_bytes).digest()).decode().rstrip("=")
        return expected[7:].rstrip("=") == digest
    parts = expected.split()
    if len(parts) >= 3 and not parts[0].startswith(("ssh-", "ecdsa-")):
        parts = parts[1:]  # línea de known_hosts: «servidor tipo clave»
    return len(parts) >= 2 and parts[0] == key_type and parts[1] == base64.b64encode(key_bytes).decode()


class SFTPSession:
    """Conexión SSH de una ubicación, con un cliente SFTP por hilo."""

    def __init__(self, location: dict, paramiko):
        self.location, self.paramiko = location, paramiko
        self._transport = None
        self._lock = threading.Lock()
        self._local = threading.local()

    def _private_key(self):
        text = self.location.get("private_key") or ""
        if not text.strip():
            return None
        pk = self.paramiko
        passphrase = self.location.get("password") or None
        for cls in (pk.Ed25519Key, pk.ECDSAKey, pk.RSAKey):
            try:
                return cls.from_private_key(io.StringIO(text), password=passphrase)
            except (pk.SSHException, ValueError):
                continue
        raise BackendError(_("The SFTP private key could not be read (format or passphrase)."))

    def _connect(self):
        loc, pk = self.location, self.paramiko
        transport = pk.Transport((loc["host"], int(loc.get("port") or 22)))
        timeout = int(loc.get("timeout") or TIMEOUT)
        transport.banner_timeout = timeout
        transport.start_client(timeout=timeout)
        server_key = transport.get_remote_server_key()
        expected = loc.get("host_key") or ""
        if expected and not host_key_matches(expected, server_key.get_name(), server_key.asbytes()):
            transport.close()
            raise BackendError(_("The key of the SFTP server does not match the configured one: it may be another "
                                 "server pretending to be it."))
        key = self._private_key()
        if key is not None:
            transport.auth_publickey(loc.get("username") or "", key)
        else:
            transport.auth_password(loc.get("username") or "", loc.get("password") or "")
        return transport

    def sftp(self):
        with self._lock:
            if self._transport is None or not self._transport.is_active():
                self._transport = self._connect()
                self._local = threading.local()
            transport = self._transport
        client = getattr(self._local, "client", None)
        if client is None or client.sock.closed:
            client = self.paramiko.SFTPClient.from_transport(transport)
            self._local.client = client
        return client


class SFTPBackend(RemoteBackend):
    kind = "sftp"
    schema = LocationSchema(
        kind="sftp",
        windows_option=True,
        label=_l("SFTP (SSH)"),
        short_label="SFTP",
        doc="Servidor SFTP (SSH): Linux, NAS, hostings.",
        place_title=_l("Server"),
        extra="sftp",
        label_placeholder=_l("Files server"),
        name_placeholder="sftp",
        credentials_help=_l("With a private key, the password is its passphrase (if it has one)."),
        options=(
            Option("host", _l("Server"), "Nombre o IP del servidor.", required=True, placeholder="files.example.com"),
            Option("port", _l("Port"), "Puerto SSH (`22`).", kind="port", default=22),
            Option("timeout", _l("Wait for the server (seconds)"),
                   "Segundos que se espera al servidor (conectar y cada respuesta) antes de dar la operación por fallida (de 1 a 600). Súbelo para un servidor lento o lejano.", kind="seconds", default=20,
                   help=_l("How long to wait for the server before giving up. Raise it for a slow or distant server.")),
            Option("path", _l("Folder"),
                   "Carpeta del servidor donde va todo: absoluta (`/srv/datos`) o relativa a la del usuario.",
                   kind="server_path", placeholder="/srv/storageweb",
                   help=_l("Absolute (/srv/files) or relative to the home folder of the user (empty = that folder).")),
            Option("host_key", _l("Server key"),
                   "Clave pública del servidor (línea de `ssh-keyscan`) o su huella `SHA256:…`. Vacía = se acepta "
                   "cualquiera (no recomendado).",
                   placeholder="ssh-ed25519 AAAAC3Nza…",
                   help=_l("Output of «ssh-keyscan server» or the SHA256 fingerprint. Empty = any key is accepted "
                           "(not recommended).")),
            Option("username", _l("User"), "Usuario.", section="credentials", required=True),
            Option("password", _l("Password"), "Contraseña, o la frase de la clave privada (secreto).",
                   kind="secret", section="credentials"),
            Option("private_key", _l("Private key"), "Clave privada (OpenSSH o PEM). Secreta.", kind="multiline",
                   section="credentials", placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"),
        ),
    )

    def __init__(self, client: SFTPSession, base: str, staging: Path, label: str = ""):
        super().__init__(staging)
        self.client, self.label = client, label
        self.absolute = base.startswith("/")
        self.base = clean_rel(base)

    @classmethod
    def connect(cls, location: dict):
        try:
            import paramiko
        except ImportError as exc:
            raise cls.missing_library("paramiko") from exc
        return SFTPSession(location, paramiko)

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> SFTPBackend:
        root = location.get("path", "")
        joined = join_rel(root, base)
        return cls(client, ("/" if root.startswith("/") else "") + joined, staging, cls.address(location))

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        root = location.get("path", "")
        rel = join_rel(root, path)
        port = int(location.get("port") or 22)
        where = f"{location['host']}" + (f":{port}" if port != 22 else "")
        user = f"{location['username']}@" if location.get("username") else ""
        home = "" if root.startswith("/") else "~/"  # absoluta o relativa a la carpeta del usuario
        return f"sftp://{user}{where}/{home}{rel}".rstrip("/")

    def describe(self) -> str:
        return self.label

    def _p(self, rel: str) -> str:
        joined = join_rel(self.base, self._clean(rel))
        return ("/" + joined) if self.absolute else (joined or ".")

    def _sftp(self):
        try:
            return self.client.sftp()
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 (red, autenticación, SSH)
            raise _error(exc) from exc

    def stat(self, rel: str) -> Entry | None:
        try:
            st = self._sftp().stat(self._p(rel))
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _error(exc) from exc
        is_dir = statmod.S_ISDIR(st.st_mode or 0)
        return Entry(name_of(clean_rel(rel)), is_dir, 0 if is_dir else int(st.st_size or 0), float(st.st_mtime or 0))

    def listdir(self, rel: str) -> list[Entry]:
        try:
            items = self._sftp().listdir_attr(self._p(rel))
        except OSError as exc:
            raise _error(exc) from exc
        entries = []
        for item in items:
            if item.filename in (".", ".."):
                continue
            is_dir = statmod.S_ISDIR(item.st_mode or 0)
            entries.append(Entry(item.filename, is_dir, 0 if is_dir else int(item.st_size or 0),
                                 float(item.st_mtime or 0)))
        return entries

    def open(self, rel: str):
        entry = self.stat(rel)
        if entry is None or entry.is_dir:
            raise FileNotFoundError(rel)
        try:
            return self._sftp().open(self._p(rel), "rb"), entry.size, entry.mtime
        except OSError as exc:
            raise _error(exc) from exc

    def mkdir(self, rel: str) -> None:
        if self.exists(rel):
            raise FileExistsError(rel)
        try:
            self._sftp().mkdir(self._p(rel))
        except OSError as exc:
            raise _error(exc) from exc

    def _move(self, rel: str, new_rel: str, entry: Entry) -> None:
        try:
            self._sftp().rename(self._p(rel), self._p(new_rel))
        except OSError as exc:
            raise _error(exc) from exc

    def _remove_tree(self, sftp, rel: str) -> None:
        for item in self.listdir(rel):
            child = join_rel(rel, item.name)
            if item.is_dir:
                self._remove_tree(sftp, child)
            else:
                sftp.remove(self._p(child))
        sftp.rmdir(self._p(rel))

    def delete(self, rel: str) -> None:
        entry = self.stat(rel)
        if entry is None:
            raise FileNotFoundError(rel)
        sftp = self._sftp()
        try:
            if entry.is_dir:
                self._remove_tree(sftp, clean_rel(rel))
            else:
                sftp.remove(self._p(rel))
        except OSError as exc:
            raise _error(exc) from exc

    def store(self, local: Path, rel: str) -> None:
        try:
            self._sftp().put(str(local), self._p(rel))
        except OSError as exc:
            raise _error(exc) from exc
        local.unlink(missing_ok=True)

    def root_exists(self) -> bool:
        return self.stat("") is not None

    def ensure_root(self, home: bool = False) -> None:
        sftp = self._sftp()
        built = ""
        for part in self.base.split("/") if self.base else []:
            built = join_rel(built, part)
            path = ("/" + built) if self.absolute else built
            try:
                sftp.stat(path)
            except FileNotFoundError:
                try:
                    sftp.mkdir(path)
                except OSError as exc:
                    raise _error(exc) from exc
            except OSError as exc:
                raise _error(exc) from exc

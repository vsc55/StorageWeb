"""Almacenamiento en un recurso compartido SMB (Windows, Samba, NAS) sin montarlo en el sistema.

Usa ``smbclient`` de la biblioteca ``smbprotocol`` (extra ``[smb]``): rutas UNC
``\\\\servidor\\recurso\\carpeta``. La sesión con cada servidor se abre una vez por proceso.
"""
from __future__ import annotations

import shutil
import stat as statmod
from pathlib import Path

from ...i18n import _, _l
from ...settings.location_types import LocationSchema, Option
from .base import BackendError, Entry, RemoteBackend, clean_rel, join_rel, name_of

COPY_BLOCK = 1024 * 1024


def _error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    if isinstance(exc, PermissionError):
        return BackendError(_("The SMB server denied the access: check the user, the password and the share permissions."))
    return BackendError(_("SMB error: %(error)s", error=exc))


class SMBBackend(RemoteBackend):
    kind = "smb"
    schema = LocationSchema(
        kind="smb",
        label=_l("SMB (Windows, Samba, NAS)"),
        short_label="SMB",
        doc="Recurso compartido de Windows, Samba o un NAS, sin montarlo en el sistema.",
        place_title=_l("Share"),
        extra="smb",
        label_placeholder=_l("Office NAS"),
        name_placeholder="nas",
        options=(
            Option("server", _l("Server"), "Nombre o IP del servidor.", required=True, placeholder="nas.example.local"),
            Option("port", _l("Port"), "Puerto (`445`).", kind="port", default=445),
            Option("share", _l("Share"), "Recurso compartido (`datos` en `\\\\nas\\datos`).", required=True,
                   placeholder="files"),
            Option("path", _l("Folder"), "Carpeta dentro del recurso donde va todo (vacía = su raíz).", kind="path",
                   placeholder="storageweb",
                   help=_l("Folder inside the share where everything goes (empty = the whole share).")),
            Option("encrypt", _l("Encrypt the traffic (SMB 3)"), "Exigir cifrado SMB 3.", kind="bool", default=True),
            Option("username", _l("User"), "Usuario (`DOMINIO\\usuario` o `usuario@dominio`).",
                   section="credentials", placeholder="DOMAIN\\storageweb"),
            Option("password", _l("Password"), "Contraseña (secreto: nunca se muestra en la web).", kind="secret",
                   section="credentials"),
        ),
    )

    @classmethod
    def connect(cls, location: dict):
        try:
            import smbclient
        except ImportError as exc:
            raise cls.missing_library("smbprotocol") from exc
        smbclient.register_session(location["server"], username=location.get("username") or None,
                                   password=location.get("password") or None,
                                   port=int(location.get("port") or 445), encrypt=bool(location.get("encrypt")))
        return smbclient

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> SMBBackend:
        return cls(client, location["server"], location["share"], join_rel(location.get("path", ""), base), staging)

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        rel = join_rel(location.get("path", ""), path).replace("/", "\\")
        return f"\\\\{location['server']}\\{location['share']}\\{rel}".rstrip("\\")

    def __init__(self, client, server: str, share: str, base: str, staging: Path):
        super().__init__(staging)
        self.client, self.server, self.share = client, server, share
        self.base = clean_rel(base)

    def describe(self) -> str:
        return f"\\\\{self.server}\\{self.share}\\{self.base.replace('/', chr(92))}".rstrip("\\")

    def _unc(self, rel: str) -> str:
        parts = [p for p in join_rel(self.base, clean_rel(rel)).split("/") if p]
        return "\\".join([f"\\\\{self.server}", self.share, *parts])

    def stat(self, rel: str) -> Entry | None:
        try:
            st = self.client.stat(self._unc(rel))
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as exc:
            if getattr(exc, "errno", None) == 2:  # ENOENT de smbprotocol (SMBOSError)
                return None
            raise _error(exc) from exc
        is_dir = statmod.S_ISDIR(st.st_mode)
        return Entry(name_of(clean_rel(rel)), is_dir, 0 if is_dir else st.st_size, st.st_mtime)

    def listdir(self, rel: str) -> list[Entry]:
        entries = []
        try:
            for item in self.client.scandir(self._unc(rel)):
                if item.name in (".", ".."):
                    continue
                is_dir = item.is_dir()
                st = item.stat()
                entries.append(Entry(item.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime))
        except OSError as exc:
            raise _error(exc) from exc
        return entries

    def open(self, rel: str):
        entry = self.stat(rel)
        if entry is None or entry.is_dir:
            raise FileNotFoundError(rel)
        try:
            return self.client.open_file(self._unc(rel), mode="rb"), entry.size, entry.mtime
        except OSError as exc:
            raise _error(exc) from exc

    def mkdir(self, rel: str) -> None:
        if self.exists(rel):
            raise FileExistsError(rel)
        try:
            self.client.mkdir(self._unc(rel))
        except OSError as exc:
            raise _error(exc) from exc

    def rename(self, rel: str, new_name: str) -> str:
        rel = clean_rel(rel)
        new_rel = join_rel(rel.rpartition("/")[0], new_name)
        if self.stat(rel) is None:
            raise FileNotFoundError(rel)
        if self.exists(new_rel):
            raise FileExistsError(new_name)
        try:
            self.client.rename(self._unc(rel), self._unc(new_rel))
        except OSError as exc:
            raise _error(exc) from exc
        return new_rel

    def _remove_tree(self, rel: str) -> None:
        for item in self.listdir(rel):
            child = join_rel(rel, item.name)
            if item.is_dir:
                self._remove_tree(child)
            else:
                self.client.remove(self._unc(child))
        self.client.rmdir(self._unc(rel))

    def delete(self, rel: str) -> None:
        entry = self.stat(rel)
        if entry is None:
            raise FileNotFoundError(rel)
        try:
            if entry.is_dir:
                self._remove_tree(clean_rel(rel))
            else:
                self.client.remove(self._unc(rel))
        except OSError as exc:
            raise _error(exc) from exc

    def store(self, local: Path, rel: str) -> None:
        try:
            with open(local, "rb") as src, self.client.open_file(self._unc(rel), mode="wb") as dst:
                shutil.copyfileobj(src, dst, COPY_BLOCK)
        except OSError as exc:
            raise _error(exc) from exc
        local.unlink(missing_ok=True)

    def root_exists(self) -> bool:
        return self.stat("") is not None

    def ensure_root(self, home: bool = False) -> None:
        try:
            self.client.makedirs(self._unc(""), exist_ok=True)
        except OSError as exc:
            raise _error(exc) from exc

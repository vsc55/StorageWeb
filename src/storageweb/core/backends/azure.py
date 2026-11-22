"""Almacenamiento en Azure Blob Storage (un contenedor de una cuenta de almacenamiento).

Usa ``azure-storage-blob`` (extra ``[azure]``). Como en S3, las carpetas son prefijos de nombre y renombrar
copia y borra blob a blob, pasando por el servidor de StorageWeb (lo común está en ``objects.py``; aquí, las
llamadas a Azure).

Autenticación: clave de la cuenta o token SAS del contenedor (lectura, escritura, borrado y lista).
``endpoint`` sirve para Azurite (pruebas) o nubes soberanas.
"""
from __future__ import annotations

from pathlib import Path

from ...i18n import _, _l
from ...settings.location_types import LocationSchema, Option
from .base import BackendError, Entry, IterStream, clean_rel, join_rel, name_of
from .objects import ObjectStoreBackend


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


def _error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    code = str(getattr(exc, "error_code", "") or "")
    if _status(exc) in (401, 403):
        return BackendError(_("Azure refused the access: check the account key or the SAS token and its "
                              "permissions."))
    if code == "ContainerNotFound":
        return BackendError(_("The Azure container does not exist."))
    return BackendError(_("Azure error: %(error)s", error=code or exc.__class__.__name__))


class AzureBlobBackend(ObjectStoreBackend):
    kind = "azure"
    schema = LocationSchema(
        kind="azure",
        label=_l("Azure Blob Storage"),
        short_label="Azure",
        doc="Contenedor de Azure Blob Storage.",
        place_title=_l("Container"),
        extra="azure",
        label_placeholder=_l("Company bucket"),
        name_placeholder="azure",
        credentials_help=_l("The account key or a SAS token of the container with read, write, delete and list."),
        options=(
            Option("account", _l("Storage account"), "Nombre de la cuenta de almacenamiento.", required=True,
                   placeholder="empresaarchivos"),
            Option("container", _l("Container"), "Contenedor.", required=True, placeholder="storageweb"),
            Option("prefix", _l("Prefix"), "Carpeta dentro del contenedor donde va todo (vacío = el contenedor).",
                   kind="path", placeholder="files",
                   help=_l("Folder inside the container where everything goes (empty = the whole container).")),
            Option("endpoint", _l("Endpoint"),
                   "Dirección del servicio si no es la pública de Azure (Azurite, nubes soberanas).",
                   kind="url", placeholder="https://ACCOUNT.blob.core.windows.net",
                   help=_l("Empty = https://ACCOUNT.blob.core.windows.net. For Azurite or sovereign clouds.")),
            Option("account_key", _l("Account key"), "Clave de la cuenta (secreto).", kind="secret",
                   section="credentials"),
            Option("sas_token", _l("SAS token"), "Token SAS del contenedor, en lugar de la clave (secreto).",
                   kind="secret", section="credentials"),
        ),
    )

    def __init__(self, container, prefix: str, staging: Path, label: str = ""):
        super().__init__(staging)
        self.container, self.label = container, label
        self.prefix = clean_rel(prefix)

    @classmethod
    def connect(cls, location: dict):
        try:
            from azure.storage.blob import ContainerClient
        except ImportError as exc:
            raise cls.missing_library("azure-storage-blob") from exc
        url = location.get("endpoint") or f"https://{location['account']}.blob.core.windows.net"
        credential = None
        if location.get("account_key"):
            credential = {"account_name": location["account"], "account_key": location["account_key"]}
        elif location.get("sas_token"):
            credential = location["sas_token"].lstrip("?")
        return ContainerClient(url, location["container"], credential=credential)

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> AzureBlobBackend:
        return cls(client, join_rel(location.get("prefix", ""), base), staging, cls.address(location))

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        rel = join_rel(location.get("prefix", ""), path)
        return f"azure://{location['account']}/{location['container']}/{rel}".rstrip("/")

    def describe(self) -> str:
        return self.label

    # ------------------------------------------------------------------ las llamadas a Azure (objects.py)
    def _fail(self, exc: Exception) -> BackendError:
        return _error(exc)

    def _read_from(self, key: str, pos: int):
        return IterStream(self.container.download_blob(key, offset=pos).chunks())

    def _put_empty(self, key: str) -> None:
        self.container.upload_blob(key, b"", overwrite=True)

    def _keys_under(self, prefix: str) -> list[str]:
        return [blob.name for blob in self.container.list_blobs(name_starts_with=prefix)]

    def _move_object(self, src: str, dst: str) -> None:
        downloader = self.container.download_blob(src)
        self.container.upload_blob(dst, IterStream(downloader.chunks()), overwrite=False, length=downloader.size)
        self.container.delete_blob(src)

    def _delete_keys(self, keys: list[str]) -> None:
        # Primero lo más profundo: los marcadores de carpeta, al final
        for name in sorted(keys, key=lambda n: (n.endswith("/"), -n.count("/"))):
            self.container.delete_blob(name)

    def _upload(self, local: Path, key: str) -> None:
        with open(local, "rb") as src:
            self.container.upload_blob(key, src, overwrite=True, length=local.stat().st_size)

    def _any_under(self, prefix: str) -> bool:
        return next(iter(self.container.list_blobs(name_starts_with=prefix)), None) is not None

    def stat(self, rel: str) -> Entry | None:
        rel = clean_rel(rel)
        try:
            if rel:
                try:
                    props = self.container.get_blob_client(self._key(rel)).get_blob_properties()
                    modified = getattr(props, "last_modified", None)
                    return Entry(name_of(rel), False, int(props.size or 0), modified.timestamp() if modified else 0.0)
                except Exception as exc:  # noqa: BLE001
                    if _status(exc) != 404 or getattr(exc, "error_code", "") == "ContainerNotFound":
                        raise
            if not rel and not self.prefix:
                self.container.get_container_properties()  # el contenedor existe y hay acceso
                return Entry("", True)
            found = self._any_under(self._dir_prefix(rel))
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc
        return Entry(name_of(rel), True) if found else None

    def listdir(self, rel: str) -> list[Entry]:
        prefix = self._dir_prefix(rel)
        entries = []
        try:
            for item in self.container.walk_blobs(name_starts_with=prefix, delimiter="/"):
                name = item.name[len(prefix):]
                if getattr(item, "size", None) is None:  # BlobPrefix: una «carpeta»
                    if name.rstrip("/"):
                        entries.append(Entry(name.rstrip("/"), True))
                    continue
                if not name:  # el marcador de la propia carpeta
                    continue
                modified = getattr(item, "last_modified", None)
                entries.append(Entry(name, False, int(item.size or 0), modified.timestamp() if modified else 0.0))
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc
        return entries

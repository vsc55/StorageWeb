"""Almacenamiento en S3 o compatible (AWS, MinIO, Wasabi, Backblaze B2, Cloudflare R2…).

Las carpetas son prefijos de clave y renombrar es copiar y borrar (lo común está en ``objects.py``; aquí, las
llamadas a S3). Requiere ``boto3`` (extra ``[s3]``).
"""
from __future__ import annotations

from pathlib import Path

from ...i18n import _, _l
from ...settings.location_types import LocationSchema, Option
from .base import BackendError, Entry, clean_rel, join_rel, name_of
from .objects import ObjectStoreBackend

NOT_FOUND = {"404", "NoSuchKey", "NotFound"}


def _code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def _error(exc: Exception) -> BackendError:
    if isinstance(exc, BackendError):
        return exc
    code = _code(exc)
    if code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "403"):
        return BackendError(_("S3 refused the access: check the access key, the secret and the bucket policy."))
    if code in ("NoSuchBucket",):
        return BackendError(_("The S3 bucket does not exist."))
    return BackendError(_("S3 error: %(error)s", error=code or exc))


class S3Backend(ObjectStoreBackend):
    kind = "s3"
    schema = LocationSchema(
        kind="s3",
        label=_l("S3 (Amazon, MinIO, Wasabi, Backblaze…)"),
        short_label="S3",
        doc="Amazon S3 o compatible (MinIO, Wasabi, Backblaze B2, Cloudflare R2…).",
        place_title=_l("Bucket"),
        extra="s3",
        label_placeholder=_l("Company bucket"),
        name_placeholder="s3",
        credentials_help=_l("Empty: the credentials of the server environment are used (variables, IAM role)."),
        options=(
            Option("bucket", _l("Bucket"), "Nombre del bucket.", required=True, placeholder="company-files"),
            Option("prefix", _l("Prefix"), "Prefijo dentro del bucket donde va todo (vacío = todo el bucket).",
                   kind="path", placeholder="storageweb",
                   help=_l("Folder inside the bucket where everything goes (empty = the whole bucket).")),
            Option("region", _l("Region"), "Región (`eu-west-1`…). Vacía = la del entorno.", placeholder="eu-west-1"),
            Option("endpoint_url", _l("Endpoint"),
                   "URL del servicio si no es AWS (MinIO, Wasabi, R2…): `https://s3.ejemplo.com`.", kind="url",
                   placeholder="https://minio.example.com:9000",
                   help=_l("Only for services other than Amazon S3 (MinIO, Wasabi, Backblaze, Cloudflare R2…).")),
            Option("path_style", _l("Path-style addresses"),
                   "Direcciones `https://servidor/bucket` en vez de `https://bucket.servidor` (MinIO).", kind="bool",
                   help=_l("endpoint/bucket instead of bucket.endpoint; MinIO usually needs it.")),
            Option("access_key", _l("Access key"), "Access Key ID. Vacía = credenciales del entorno.",
                   section="credentials"),
            Option("secret_key", _l("Secret key"), "Secret Access Key (secreto: nunca se muestra en la web).",
                   kind="secret", section="credentials"),
        ),
    )

    def __init__(self, client, bucket: str, prefix: str, staging: Path):
        super().__init__(staging)
        self.client, self.bucket = client, bucket
        self.prefix = clean_rel(prefix)

    @classmethod
    def connect(cls, location: dict):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise cls.missing_library("boto3") from exc
        style = "path" if location.get("path_style") else "auto"
        return boto3.client("s3", endpoint_url=location.get("endpoint_url") or None,
                            region_name=location.get("region") or None,
                            aws_access_key_id=location.get("access_key") or None,
                            aws_secret_access_key=location.get("secret_key") or None,
                            config=Config(s3={"addressing_style": style}, retries={"max_attempts": 3}))

    @classmethod
    def create(cls, client, location: dict, base: str, staging: Path) -> S3Backend:
        return cls(client, location["bucket"], join_rel(location.get("prefix", ""), base), staging)

    @classmethod
    def address(cls, location: dict, path: str = "") -> str:
        return f"s3://{location['bucket']}/{join_rel(location.get('prefix', ''), path)}".rstrip("/")

    def describe(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}".rstrip("/")

    # ------------------------------------------------------------------ las llamadas a S3 (objects.py)
    def _fail(self, exc: Exception) -> BackendError:
        return _error(exc)

    def _read_from(self, key: str, pos: int):
        return self.client.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={pos}-")["Body"]

    def _put_empty(self, key: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=b"")

    def _move_object(self, src: str, dst: str) -> None:
        self.client.copy_object(Bucket=self.bucket, Key=dst, CopySource={"Bucket": self.bucket, "Key": src})
        self.client.delete_object(Bucket=self.bucket, Key=src)

    def _delete_keys(self, keys: list[str]) -> None:
        for i in range(0, len(keys), 1000):  # máximo de delete_objects
            self.client.delete_objects(Bucket=self.bucket,
                                       Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]], "Quiet": True})

    def _upload(self, local: Path, key: str) -> None:
        self.client.upload_file(str(local), self.bucket, key)  # multipart automático si es grande

    def _any_under(self, prefix: str) -> bool:
        page = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1)
        return bool(page.get("KeyCount", len(page.get("Contents", []))))

    def _keys_under(self, prefix: str):
        token = None
        while True:
            args = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            for obj in page.get("Contents", []):
                yield obj["Key"]
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")

    def stat(self, rel: str) -> Entry | None:
        rel = clean_rel(rel)
        try:
            if rel:
                try:
                    head = self.client.head_object(Bucket=self.bucket, Key=self._key(rel))
                    return Entry(name_of(rel), False, int(head.get("ContentLength", 0)),
                                 head["LastModified"].timestamp() if head.get("LastModified") else 0.0)
                except Exception as exc:  # noqa: BLE001
                    if _code(exc) not in NOT_FOUND:
                        raise
            if not rel and not self.prefix:
                return Entry("", True)
            found = self._any_under(self._dir_prefix(rel))
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc
        return Entry(name_of(rel), True) if found else None

    def listdir(self, rel: str) -> list[Entry]:
        prefix = self._dir_prefix(rel)
        entries, token = [], None
        try:
            while True:
                args = {"Bucket": self.bucket, "Prefix": prefix, "Delimiter": "/"}
                if token:
                    args["ContinuationToken"] = token
                page = self.client.list_objects_v2(**args)
                for common in page.get("CommonPrefixes", []):
                    entries.append(Entry(common["Prefix"][len(prefix):].rstrip("/"), True))
                for obj in page.get("Contents", []):
                    name = obj["Key"][len(prefix):]
                    if not name:  # el marcador de la propia carpeta
                        continue
                    entries.append(Entry(name, False, int(obj.get("Size", 0)),
                                         obj["LastModified"].timestamp() if obj.get("LastModified") else 0.0))
                if not page.get("IsTruncated"):
                    return entries
                token = page.get("NextContinuationToken")
        except Exception as exc:  # noqa: BLE001
            raise _error(exc) from exc

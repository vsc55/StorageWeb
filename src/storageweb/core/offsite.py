"""Copias de seguridad fuera del servidor (``maintenance.offsite_*``).

Cada copia (la automática, la de la web y la de ``storageweb backup``) se envía también a una ubicación de
almacenamiento (S3, SMB, SFTP…), a la carpeta ``offsite_path``, que conserva las ``offsite_keep`` más recientes
con fecha (las de antes de restaurar y las subidas a mano no se borran solas). Si el servidor se pierde, uno
nuevo con la misma ubicación las lista y se trae la que quiera (:func:`fetch`) para restaurarla como cualquier
otra. Se envían tal cual: llevan la base de datos y las claves, así que la ubicación debe ser solo de los
administradores.
"""
from __future__ import annotations

import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import backends, backup
from .backup import BackupError
from .security import UPLOAD_TMP_PREFIX
from ..i18n import _


def enabled(cfg: dict) -> bool:
    return bool((cfg.get("maintenance") or {}).get("offsite_location"))


def _location(cfg: dict) -> dict:
    name = cfg["maintenance"]["offsite_location"]
    loc = backends.find_location(cfg, name)
    if loc is None:
        raise BackupError(_("There is no storage location named %(name)s.", name=name))
    return loc


def where(cfg: dict) -> str:
    """Dirección legible de la carpeta de las copias (``s3://copias/storageweb-backups``)."""
    try:
        return backends.address(_location(cfg), cfg["maintenance"]["offsite_path"])
    except (BackupError, backends.BackendError):
        return cfg["maintenance"]["offsite_location"]


def _backend(cfg: dict) -> backends.Backend:
    return backends.backend_for(_location(cfg), cfg["maintenance"]["offsite_path"], backends.staging_dir(cfg))


def _is_backup(name: str) -> bool:
    return name.startswith(backup.PREFIX) and name.endswith(backup.SUFFIX) and backends.is_safe_name(name)


def send(cfg: dict, archive: Path) -> list[str]:
    """Envía ``archive`` y borra las más antiguas que sobran. Devuelve las borradas; :class:`BackupError` si
    no se pudo enviar."""
    try:
        target = _backend(cfg)
        target.ensure_root()
        tmp = target.staging_dir("") / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
        try:
            shutil.copyfile(archive, tmp)          # store() se queda con el archivo: se envía una copia
            target.store(tmp, archive.name)
        finally:
            tmp.unlink(missing_ok=True)
        return _prune(target, cfg["maintenance"]["offsite_keep"])
    except backends.BackendError as exc:
        raise BackupError(exc.message) from exc
    except OSError as exc:
        raise BackupError(str(exc) or exc.__class__.__name__) from exc


def _entries(target: backends.Backend) -> list:
    """Las copias de la ubicación, de la más antigua a la más reciente."""
    found = [e for e in target.listdir("") if not e.is_dir and _is_backup(e.name)]
    return sorted(found, key=lambda e: (e.mtime or 0, e.name))


def _prune(target: backends.Backend, keep: int) -> list[str]:
    dated = [e for e in _entries(target) if backup._dated(Path(e.name))]   # noqa: SLF001 (misma regla)
    removed = [e.name for e in dated[:-keep]] if keep > 0 else []
    for name in removed:
        target.delete(name)
    return removed


def list_remote(cfg: dict) -> list[dict]:
    """Las copias de la ubicación, la más reciente primero: ``{name, size, created}``."""
    try:
        entries = _entries(_backend(cfg))
    except backends.BackendError as exc:
        raise BackupError(exc.message) from exc
    except OSError as exc:
        raise BackupError(str(exc) or exc.__class__.__name__) from exc
    return [{"name": e.name, "size": e.size,
             "created": datetime.fromtimestamp(e.mtime, timezone.utc).isoformat(timespec="seconds")
             if e.mtime else ""} for e in reversed(entries)]


def fetch(cfg: dict, name: str, into: Path) -> Path:
    """Trae una copia de la ubicación a ``into`` (la carpeta de copias de este servidor) para restaurarla. Si ya
    hay una con ese nombre, no la descarga otra vez."""
    if not _is_backup(name):
        raise BackupError(_("The backup %(name)s does not exist.", name=name))
    final = into / name
    if final.exists():
        return final
    into.mkdir(parents=True, exist_ok=True)
    tmp = into / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
    try:
        source = _backend(cfg)
        if source.stat(name) is None:
            raise BackupError(_("The backup %(name)s does not exist.", name=name))
        fh, _size, _mtime = source.open(name)
        try:
            with open(tmp, "wb") as out:
                shutil.copyfileobj(fh, out, 1024 * 1024)
        finally:
            fh.close()
        backup.check_restorable(tmp)
        tmp.chmod(0o600)                           # contiene hashes de contraseñas y secretos
        tmp.replace(final)
        return final
    except backends.BackendError as exc:
        raise BackupError(exc.message) from exc
    finally:
        tmp.unlink(missing_ok=True)

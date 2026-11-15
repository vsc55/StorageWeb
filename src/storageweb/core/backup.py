"""Copias de seguridad de la base de datos y la configuración.

Una copia es un ``.tar.gz`` con:

    manifest.json    formato, versión de StorageWeb, versión del esquema y fecha
    storageweb.db    copia consistente de SQLite (API de backup en línea: válida con el servicio arrancado)
    config.json      el fichero de configuración, si se puede leer
    secret_key       la clave de sesiones generada, si existe
    secrets.key      la clave con la que están cifrados los secretos de los ajustes (``settings.secretbox``)

Los archivos de los usuarios (homes y carpetas compartidas) NO se incluyen: pueden ocupar mucho
y se copian mejor con herramientas incrementales (rsync, borg, restic, snapshots del sistema de
ficheros). Ver docs/administracion/copias-seguridad.md.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..db import available_migrations, connect, init_db, schema_version
from ..i18n import _
from ..settings import secretbox

FORMAT = 1
PREFIX = "storageweb-backup-"
SUFFIX = ".tar.gz"
_MEMBERS = {"manifest.json", "storageweb.db", "config.json", "secret_key", secretbox.KEY_FILE}


class BackupError(Exception):
    pass


def _sqlite_copy(src_path: str, dst_path: Path) -> int:
    """Copia consistente con la API de backup de SQLite. Devuelve la versión del esquema."""
    src = sqlite3.connect(src_path, timeout=30)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError(_("The database copy fails PRAGMA integrity_check"))
        return dst.execute("PRAGMA user_version").fetchone()[0]
    finally:
        dst.close()
        src.close()


def create(cfg: dict, output_dir: Path, keep: int | None = None, label: str = "") -> Path:
    """Crea una copia en ``output_dir`` y, si ``keep`` se indica, borra las más antiguas. ``label`` va en el
    nombre (``storageweb-backup-<label>-<fecha>``): esas no entran en la rotación."""
    if not Path(cfg["database"]).exists():
        raise BackupError(_("The database %(path)s does not exist", path=cfg["database"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{PREFIX}{label}-{stamp}" if label else f"{PREFIX}{stamp}"
    final = output_dir / f"{base}{SUFFIX}"
    n = 1
    while final.exists():
        final = output_dir / f"{base}-{n}{SUFFIX}"
        n += 1

    with tempfile.TemporaryDirectory(dir=output_dir, prefix=".backup-") as tmp:
        tmp_dir = Path(tmp)
        db_copy = tmp_dir / "storageweb.db"
        version = _sqlite_copy(cfg["database"], db_copy)
        included = ["storageweb.db"]
        extra: list[tuple[Path, str]] = []
        cfg_path = Path(cfg.get("_config_path", ""))
        if cfg_path.is_file() and os.access(cfg_path, os.R_OK):
            extra.append((cfg_path, "config.json"))
        key_file = Path(cfg["data_dir"]) / "secret_key"
        if key_file.is_file():
            extra.append((key_file, "secret_key"))
        # La clave de los secretos: del fichero o, si viene del entorno, la que se usa (sin ella, la copia no
        # sirve para restaurar los secretos en otro servidor)
        secrets_text = os.environ.get(secretbox.ENV, "").strip()
        secrets_file = secretbox.key_path(cfg["data_dir"])
        if not secrets_text and secrets_file.is_file():
            secrets_text = secrets_file.read_text(encoding="utf-8").strip()
        if secrets_text:
            key_copy = tmp_dir / secretbox.KEY_FILE
            key_copy.write_text(secrets_text, encoding="utf-8")
            extra.append((key_copy, secretbox.KEY_FILE))
        included += [name for _, name in extra]
        manifest = {"format": FORMAT, "storageweb_version": __version__, "schema_version": version,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "files": included}

        partial = tmp_dir / "backup.tar.gz"
        with tarfile.open(partial, "w:gz") as tar:
            data = json.dumps(manifest, indent=2).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            tar.addfile(info, io.BytesIO(data))
            tar.add(db_copy, arcname="storageweb.db")
            for path, name in extra:
                tar.add(path, arcname=name)
        os.chmod(partial, 0o600)  # contiene hashes de contraseñas y secretos
        os.replace(partial, final)

    if keep:
        prune(output_dir, keep)
    return final


def list_backups(output_dir: Path) -> list[Path]:
    """Las copias, de la más antigua a la más reciente (por fecha del fichero)."""
    return sorted(output_dir.glob(f"{PREFIX}*{SUFFIX}"), key=lambda p: (p.stat().st_mtime, p.name))


def _dated(path: Path) -> bool:
    """Copia con fecha hecha por StorageWeb (``storageweb-backup-20261115-…``): las que entran en la rotación.
    Las de antes de restaurar y las subidas desde la web se quedan hasta que se borren a mano."""
    return path.name[len(PREFIX):len(PREFIX) + 1].isdigit()


def prune(output_dir: Path, keep: int) -> list[Path]:
    """Conserva las ``keep`` copias con fecha más recientes y borra el resto. Devuelve las borradas."""
    backups = [p for p in list_backups(output_dir) if _dated(p)]  # de la más antigua a la más reciente
    removed = backups[:-keep] if keep > 0 else []
    for path in removed:
        path.unlink()
    return removed


def _open(archive: Path) -> tuple[tarfile.TarFile, dict]:
    try:
        tar = tarfile.open(archive, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise BackupError(_("Not a valid backup: %(error)s", error=exc)) from exc
    names = set(tar.getnames())
    unknown = names - _MEMBERS
    if unknown or "manifest.json" not in names or "storageweb.db" not in names:
        tar.close()
        raise BackupError(_("Unexpected content in the backup: %(names)s", names=sorted(unknown) or sorted(names)))
    for member in tar.getmembers():
        if not member.isfile():
            tar.close()
            raise BackupError(_("Entry not allowed in the backup: %(name)s", name=member.name))
    manifest = json.load(tar.extractfile("manifest.json"))
    if manifest.get("format") != FORMAT:
        tar.close()
        raise BackupError(_("Unsupported backup format: %(format)s", format=manifest.get("format")))
    return tar, manifest


def read_manifest(archive: Path) -> dict:
    tar, manifest = _open(archive)
    tar.close()
    return manifest


def _rekey(db_path: Path, tar: tarfile.TarFile, data_dir: str) -> None:
    """Los secretos de la base de datos restaurada estaban cifrados con la clave de la copia: se vuelven a cifrar
    con la de este servidor (si es la misma, no cambia nada; si este no tenía, se queda con la de la copia)."""
    backup_key = None
    if secretbox.KEY_FILE in tar.getnames():
        text = tar.extractfile(secretbox.KEY_FILE).read().decode("utf-8").strip()
        backup_key = secretbox.parse_key(text)
        if not os.environ.get(secretbox.ENV) and not secretbox.key_path(data_dir).exists():
            secretbox.write_key(data_dir, text)  # servidor nuevo: la clave de la copia
    current = secretbox.load_key(data_dir)
    conn = connect(str(db_path))
    try:
        secretbox.rekey(conn, backup_key, current)
    finally:
        conn.close()


def check_restorable(archive: Path) -> dict:
    """El manifiesto de una copia que se puede restaurar aquí; :class:`BackupError` si no (formato, contenido o
    una versión de StorageWeb más nueva que esta)."""
    tar, manifest = _open(archive)
    tar.close()
    if manifest.get("schema_version", 0) > available_migrations()[-1][0]:
        raise BackupError(_("The backup is from a newer StorageWeb version: upgrade before restoring"))
    return manifest


def restore_online(cfg: dict, archive: Path) -> dict:
    """Restaura la base de datos de una copia **con el servicio en marcha**, con la API de copia de SQLite sobre
    la base de datos en uso (otras conexiones esperan; nunca ven un fichero a medias). Después aplica las
    migraciones pendientes. No toca ``config.json`` ni la ``secret_key``. El llamante pone el servicio en
    mantenimiento y hace antes una copia de lo actual (``core.maintenance.restore_backup``)."""
    db_path = Path(cfg["database"])
    tar, manifest = _open(archive)
    with tar:
        if manifest.get("schema_version", 0) > available_migrations()[-1][0]:
            raise BackupError(_("The backup is from a newer StorageWeb version: upgrade before restoring"))
        with tempfile.TemporaryDirectory(dir=db_path.parent, prefix=".restore-") as tmp:
            source_path = Path(tmp) / "storageweb.db"
            with open(source_path, "wb") as fh:
                shutil.copyfileobj(tar.extractfile("storageweb.db"), fh)
            source = sqlite3.connect(source_path)
            try:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError(_("The database in the backup is damaged"))
                target = sqlite3.connect(db_path, timeout=60)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
        init_db(str(db_path))
        _rekey(db_path, tar, cfg["data_dir"])
    conn = connect(str(db_path))
    try:
        manifest["restored_schema_version"] = schema_version(conn)
    finally:
        conn.close()
    return manifest


def restore(cfg: dict, archive: Path, *, force: bool = False, config_to: Path | None = None) -> dict:
    """Restaura la base de datos (y la secret_key) de una copia. El servicio debe estar parado.

    Si ya existe una base de datos se exige ``force`` y se guarda antes una copia
    ``<bd>.antes-de-restaurar-<fecha>``. Tras restaurar se aplican las migraciones pendientes.
    """
    tar, manifest = _open(archive)
    with tar:
        latest = available_migrations()[-1][0]
        if manifest.get("schema_version", 0) > latest:
            raise BackupError(_("The backup is from a newer StorageWeb version: upgrade before restoring"))

        db_path = Path(cfg["database"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            if not force:
                raise BackupError(_("%(path)s already exists; use --force to replace it", path=db_path))
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            shutil.copy2(db_path, db_path.with_name(f"{db_path.name}.antes-de-restaurar-{stamp}"))

        tmp_db = db_path.with_name(f".{db_path.name}.restaurando")
        with open(tmp_db, "wb") as fh:
            shutil.copyfileobj(tar.extractfile("storageweb.db"), fh)
        check = sqlite3.connect(tmp_db)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError(_("The database in the backup is damaged"))
        finally:
            check.close()
        # Los ficheros WAL de la base de datos anterior no deben aplicarse a la restaurada
        for suffix in ("-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        os.replace(tmp_db, db_path)

        if "secret_key" in tar.getnames() and not cfg.get("secret_key"):
            key_file = Path(cfg["data_dir"]) / "secret_key"
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_bytes(tar.extractfile("secret_key").read())
            os.chmod(key_file, 0o600)

        if config_to is not None:
            if "config.json" not in tar.getnames():
                raise BackupError(_("The backup does not include config.json"))
            config_to.write_bytes(tar.extractfile("config.json").read())

        init_db(str(db_path))
        _rekey(db_path, tar, cfg["data_dir"])
    conn = connect(str(db_path))
    try:
        manifest["restored_schema_version"] = schema_version(conn)
    finally:
        conn.close()
    return manifest

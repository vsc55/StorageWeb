"""Mantenimiento: tareas periódicas, retención de la auditoría, compactación y copias automáticas.

Las tareas se declaran con el decorador :func:`task` en el módulo que sabe de cada cosa (aquí las
sesiones, la auditoría y las copias; los bloqueos de IP en ``ipban``…). ``run_due`` ejecuta las que
toquen según su intervalo y apunta cuándo se hizo cada una en el documento ``maintenance_state`` de
la tabla ``settings``. La capa web la llama de vez en cuando en un hilo aparte.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlite3 import Connection

from .. import registry, siem
from ..db.repositories import audit, sessions
from ..db.repositories import settings as settings_repo
from ..i18n import _, format_datetime
from . import backup, offsite
from .alerts import alert, source

STATE_KEY = "maintenance_state"
_log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def backup_dir(cfg: dict) -> Path:
    """Carpeta de las copias (la misma que usa ``storageweb backup`` por defecto)."""
    return Path(cfg["data_dir"]) / "backups"


def state(conn: Connection) -> dict:
    return settings_repo.get(conn, STATE_KEY) or {}


def _mark(conn: Connection, task: str) -> None:
    _put_state(conn, task, _iso(_now()))


def _put_state(conn: Connection, key: str, value) -> None:
    current = state(conn)
    current[key] = value
    settings_repo.put(conn, STATE_KEY, current, "system")


def put_state(conn: Connection, key: str, value) -> None:
    """Guarda ``value`` en ``maintenance_state`` (lo leen la página que lo enseña y los avisos del Resumen)."""
    _put_state(conn, key, value)


def db_stats(conn: Connection, database: str) -> dict:
    size = sum(Path(database + suffix).stat().st_size for suffix in ("", "-wal") if Path(database + suffix).exists())
    tables = {}
    for table in ("users", "audit_log", "sessions", "api_tokens", "ip_rules", "groups"):
        tables[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 (nombres fijos)
    oldest = conn.execute("SELECT MIN(ts) FROM audit_log").fetchone()[0]
    return {"size": size, "tables": tables, "audit_oldest": oldest}


def purge_audit(conn: Connection, days: int) -> int:
    """Borra las entradas de auditoría de hace más de ``days`` días."""
    if days <= 0:
        return 0
    cur = conn.execute("DELETE FROM audit_log WHERE ts < ?", (_iso(_now() - timedelta(days=days)),))
    conn.commit()
    return cur.rowcount


def vacuum(conn: Connection, database: str) -> tuple[int, int]:
    """Compacta la base de datos. Devuelve (tamaño antes, tamaño después)."""
    before = db_stats(conn, database)["size"]
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return before, db_stats(conn, database)["size"]


def list_backups(cfg: dict) -> list[dict]:
    result = []
    for path in reversed(backup.list_backups(backup_dir(cfg))):
        stat = path.stat()
        result.append({"name": path.name, "size": stat.st_size,
                       "created": _iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc))})
    return result


def backup_path(cfg: dict, name: str) -> Path | None:
    """Ruta de una copia por su nombre (solo nombres de copias existentes: nada de rutas)."""
    if os.sep in name or "/" in name or name.startswith("."):
        return None
    path = backup_dir(cfg) / name
    return path if path in backup.list_backups(backup_dir(cfg)) else None


def create_backup(cfg: dict, prune: bool = True) -> Path:
    keep = cfg["maintenance"]["backup_keep"] if prune else None
    return backup.create(cfg, backup_dir(cfg), keep=keep or None)


def send_offsite(conn: Connection, cfg: dict, path: Path, actor: str) -> str | None:
    """Envía la copia ``path`` fuera del servidor, si está configurado (``maintenance.offsite_location``), y
    apunta el resultado (el aviso del *Resumen* y la página de copias lo leen). Devuelve el error o ``None``.
    ``cfg`` son los ajustes efectivos (necesita las ubicaciones)."""
    if not offsite.enabled(cfg):
        return None
    where = offsite.where(cfg)
    try:
        removed = offsite.send(cfg, path)
    except backup.BackupError as exc:
        _log.warning("Could not send the backup %s to %s: %s", path.name, where, exc)
        _put_state(conn, "offsite", {"at": _iso(_now()), "ok": False, "name": path.name, "error": str(exc)[:300]})
        audit.log(conn, "backup_offsite_failed", path.name, username=actor, detail=f"{where}: {exc}"[:300])
        return str(exc)
    _put_state(conn, "offsite", {"at": _iso(_now()), "ok": True, "name": path.name, "error": ""})
    audit.log(conn, "backup_offsite", path.name, username=actor,
              detail=where + (f" (-{len(removed)})" if removed else ""))
    return None


# --------------------------------------------------------------------------- restaurar con el servicio en marcha

_restoring = threading.Lock()
RESTORING = threading.Event()   # mientras está puesto, la web responde 503 «en mantenimiento»
SAFETY_PREFIX = "antes-de-restaurar"


def add_backup(cfg: dict, upload: Path, filename: str) -> Path:
    """Guarda una copia subida desde la web (de este u otro servidor) junto a las demás, si es válida."""
    backup.check_restorable(upload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = Path(filename or "").name
    if not (name.startswith(backup.PREFIX) and name.endswith(backup.SUFFIX)) or "/" in name or "\\" in name:
        name = f"{backup.PREFIX}subida-{stamp}{backup.SUFFIX}"
    target = backup_dir(cfg) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while target.exists():
        target = backup_dir(cfg) / name.replace(backup.SUFFIX, f"-{n}{backup.SUFFIX}")
        n += 1
    shutil.copyfile(upload, target)
    os.chmod(target, 0o600)  # contiene hashes de contraseñas y secretos
    return target


def restore_backup(conn_factory: Callable[[], Connection], cfg: dict, name: str, *, actor: str,
                   ip: str | None = None) -> dict:
    """Restaura la copia ``name`` con el servicio en marcha:

    1. pone el servicio en mantenimiento (:data:`RESTORING`: el resto de peticiones reciben 503);
    2. hace antes una copia de lo actual (no se borra en la rotación; queda en la lista para volver atrás);
    3. sustituye la base de datos (``backup.restore_online``) y aplica las migraciones;
    4. cierra todas las sesiones (las de la copia no deben revivir) y anota la restauración en la auditoría.

    ``conn_factory`` abre una conexión nueva (la de la petición puede quedar vieja). Devuelve el manifiesto
    con ``safety`` (el nombre de la copia previa). :class:`backup.BackupError` si no se puede.
    """
    path = backup_path(cfg, name)
    if path is None:
        raise backup.BackupError(_("The backup %(name)s does not exist.", name=name))
    backup.check_restorable(path)
    if not _restoring.acquire(blocking=False):
        raise backup.BackupError(_("Another restore is already in progress."))
    RESTORING.set()
    try:
        named = backup.create(cfg, backup_dir(cfg), keep=None, label=SAFETY_PREFIX)
        manifest = backup.restore_online(cfg, path)
        conn = conn_factory()
        try:
            closed = sessions.delete_all(conn)  # las de la copia no deben revivir
            audit.log(conn, "backup_restored", name, username=actor, ip=ip,
                      detail=f"schema {manifest.get('schema_version')}->{manifest.get('restored_schema_version')}; "
                             f"safety {named.name}; sessions {closed}")
        finally:
            conn.close()
        manifest["safety"] = named.name
        return manifest
    finally:
        RESTORING.clear()
        _restoring.release()


# --------------------------------------------------------------------------- tareas periódicas

@dataclass(frozen=True)
class Task:
    name: str
    every: Callable[[dict], float | None]  # horas entre ejecuciones según los ajustes; 0 o None = desactivada
    run: Callable[[Connection, dict], None]
    order: int = 50


_TASKS: dict[str, Task] = {}


def task(name: str, every: Callable[[dict], float | None], order: int = 50):
    """Registra ``fn(conn, cfg)`` como tarea periódica. ``name`` es la clave en ``maintenance_state``."""
    def decorate(fn):
        _TASKS.setdefault(name, Task(name, every, fn, order))
        return fn
    return decorate


def tasks() -> list[Task]:
    registry.import_submodules("storageweb.core")  # las tareas se registran al importar su módulo
    return sorted(_TASKS.values(), key=lambda t: (t.order, t.name))


def run_due(conn: Connection, cfg: dict) -> list[str]:
    """Ejecuta las tareas pendientes. Devuelve las que se hicieron (también las que fallaron)."""
    done = []
    current = state(conn)
    for t in tasks():
        hours = t.every(cfg)
        last = current.get(t.name)
        if not hours or (last and last >= _iso(_now() - timedelta(hours=hours))):
            continue
        try:
            t.run(conn, cfg)
        except Exception:  # noqa: BLE001 (una tarea rota no para las demás; se reintenta en su intervalo)
            _log.exception("Maintenance task %s failed", t.name)
        _mark(conn, t.name)
        done.append(t.name)
    return done


@task("cleanup", every=lambda cfg: 1, order=10)
def _close_idle_sessions(conn: Connection, cfg: dict) -> None:
    sessions.delete_idle(conn, _iso(_now() - timedelta(hours=cfg["session"]["lifetime_hours"])))


@task("audit_purge", every=lambda cfg: 24 if cfg["maintenance"]["audit_retention_days"] else 0, order=20)
def _purge_audit(conn: Connection, cfg: dict) -> None:
    removed = purge_audit(conn, cfg["maintenance"]["audit_retention_days"])
    if removed:
        audit.log(conn, "audit_purged", None, username="system", detail=str(removed))


@task("backup", every=lambda cfg: cfg["maintenance"]["backup_interval_hours"], order=30)
def _automatic_backup(conn: Connection, cfg: dict) -> None:
    try:
        path = create_backup(cfg)
    except Exception as exc:  # noqa: BLE001 (se registra y se reintenta en el siguiente intervalo)
        _log.exception("Automatic backup failed")
        audit.log(conn, "backup_failed", None, username="system", detail=str(exc)[:200])
    else:
        audit.log(conn, "backup_created", path.name, username="system", detail="auto")
        send_offsite(conn, cfg, path, "system")


@source("audit_forward", order=35)
def _audit_forward_failing(ctx):
    """El reenvío de la auditoría al SIEM falla (lo último que se intentó no llegó)."""
    status = siem.FORWARDER.status()
    if not status["active"] or not status["failing"]:
        return []
    return [alert("warn", "audit_forward_failing", _("The audit log is not reaching the SIEM"),
                  status["last_error"], "audit_settings", _("See the settings"), "siem-title")]


@source("offsite_backup", order=31)
def _offsite_failed(ctx):
    last = ctx.maint_state.get("offsite")
    if not offsite.enabled(ctx.cfg) or not isinstance(last, dict) or last.get("ok", True):
        return []
    return [alert("danger", "offsite_failed", _("The last backup could not be sent outside the server"),
                  last.get("error") or "", "backups", _("See the backups"))]


@source("backups", order=30)
def _stale_backups(ctx):
    hours = ctx.cfg["maintenance"]["backup_interval_hours"]
    if not hours:
        return []
    backups = list_backups(ctx.boot)
    newest = backups[0]["created"] if backups else None
    limit = _now() - timedelta(hours=hours * 2 + 1)
    tried = ctx.maint_state.get("backup")  # sin copias y sin intento aún: recién instalado, no es un aviso
    if (newest is None and tried) or (newest is not None and datetime.fromisoformat(newest) < limit):
        return [alert("warn", "backup_stale", _("Automatic backups are not being made"),
                      _("The newest backup is from %(date)s.", date=format_datetime(newest)) if newest
                      else _("There is no backup yet."), "backups", _("See the backups"))]
    return []

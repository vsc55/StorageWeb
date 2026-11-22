"""Fechas en UTC y en ISO 8601 (con segundos, sin microsegundos): como se guardan en la base de datos, en la
auditoría y en el estado del mantenimiento, y por eso se comparan como texto. Sin dependencias: lo usan ``db``,
``core``, ``settings`` y ``web``."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(when: datetime) -> str:
    """``2026-11-22T10:30:00+00:00``."""
    return when.isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(utcnow())


def iso_ago(**delta) -> str:
    """Hace tanto (``days=``, ``hours=``, ``minutes=``…), en ISO: el límite de «lo anterior a»."""
    return iso(utcnow() - timedelta(**delta))


def iso_in(**delta) -> str:
    """Dentro de tanto, en ISO: una caducidad."""
    return iso(utcnow() + timedelta(**delta))


def iso_from_ts(ts: float) -> str:
    """Un instante de ``time.time()`` o de ``stat().st_mtime``, en ISO y en UTC."""
    return iso(datetime.fromtimestamp(ts, timezone.utc))


def file_stamp() -> str:
    """Para nombres de archivo (copias de seguridad): ``20261122-103000``."""
    return utcnow().strftime("%Y%m%d-%H%M%S")

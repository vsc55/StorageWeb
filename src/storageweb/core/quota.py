"""Cuotas de espacio de las carpetas (personales y compartidas).

La cuota de una carpeta es ``root["quota_mb"]`` (0 = sin cuota): la personal sale del usuario
(``users.quota_mb``), de sus grupos (``storage.group_quotas``) o de ``storage.home_quota_mb``; la compartida, de
``storage.shares[].quota_mb``. Avisan a partir del 90 % y, con ``storage.quota_enforce`` (por defecto), además
**impiden escribir** lo que no quepa: :func:`check` antes de cada subida, copia o traslado a otra carpeta.

El uso se mide sumando lo que hay en la carpeta (todo, también lo oculto: ocupa espacio igual) y se guarda en
memoria. Como hacen otros (Nextcloud, ownCloud), **se lleva la cuenta** de lo que escribe y borra StorageWeb
(:func:`record`: subidas, copias, ediciones por la web, la API y WebDAV) y **se reconcilia en segundo plano**: si
la medida tiene más de ``storage.quota_refresh_minutes`` (o algo la dejó dudosa, :func:`invalidate`, p. ej. al
borrar una carpeta), se vuelve a medir en un hilo aparte, con más tiempo que en una petición, mientras se sigue
usando la anterior. Así se ve lo que otros cambien directamente en el almacenamiento (otro programa en el mismo
bucket o NAS) sin recorrer nunca una carpeta remota grande mientras alguien espera. Solo la primera medida de una
carpeta desde que arranca el servicio se hace en el momento (acotada a :data:`MAX_SECONDS`; la tarea
``monitoring`` ya mide las compartidas al arrancar): sin ella no se podría aplicar la cuota. Si no da tiempo a
recorrerla entera, el uso es «al menos» lo contado (``complete = False``).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .. import metrics
from ..i18n import _, format_age, format_size
from . import backends
from ..settings.errors import UserError
from ..clock import iso_from_ts

MB = 1024 * 1024
WARN_PERCENT = 90        # a partir de aquí se avisa (storage.quota_warn_percent; este, sin ajustes)
MAX_SECONDS = 10.0       # la primera medida, en la petición
MAX_ENTRIES = 500_000
BACKGROUND_SECONDS = 600.0   # las de segundo plano: nadie espera
BACKGROUND_ENTRIES = 10_000_000
BACKGROUND_WORKERS = 2       # recorridos a la vez como mucho


@dataclass
class _Usage:
    measured: float      # time.monotonic() de la medida
    at: float            # time.time() de la medida (para «medido hace X»)
    used: int
    complete: bool
    stale: bool = False  # hay que volver a medirla (se usa mientras tanto)


_cache: dict[str, _Usage] = {}
_running: set[str] = set()
_lock = threading.Lock()
_workers = threading.BoundedSemaphore(BACKGROUND_WORKERS)
_refresh_seconds = 60 * 60.0
_warn_percent = WARN_PERCENT


def configure(refresh_minutes: int, warn_percent: int = WARN_PERCENT) -> None:
    """``storage.quota_refresh_minutes``: cada cuánto se vuelve a medir una carpeta en segundo plano;
    ``storage.quota_warn_percent``: desde qué porcentaje se avisa."""
    global _refresh_seconds, _warn_percent  # noqa: PLW0603 (ajustes del proceso)
    _refresh_seconds = max(int(refresh_minutes or 0), 1) * 60.0
    _warn_percent = int(warn_percent or WARN_PERCENT)


def _key(root: dict) -> str:
    return str(root.get("where") or f"{root.get('location', '')}:{root.get('path')}")


class QuotaExceeded(UserError):
    """No cabe en la cuota de la carpeta. ``message`` es para la persona (HTTP 507)."""


def limit_bytes(root: dict) -> int:
    return int(root.get("quota_mb") or 0) * MB


def enforced(cfg: dict) -> bool:
    return bool(cfg["storage"].get("quota_enforce", True))


def check(root: dict, cfg: dict, incoming: int, freed: int = 0) -> None:
    """:class:`QuotaExceeded` si escribir ``incoming`` bytes (liberando ``freed``, p. ej. el archivo que se
    sobrescribe) deja la carpeta por encima de su cuota. Sin cuota, o si no se aplican, no hace nada."""
    limit = limit_bytes(root)
    if limit <= 0 or not enforced(cfg):
        return
    used, _complete = usage(root)
    if used - max(freed, 0) + max(incoming, 0) > limit:
        metrics.inc("storageweb_quota_rejections_total")
        free = max(limit - used, 0)
        raise QuotaExceeded(_("Not enough quota in «%(folder)s»: %(free)s free of %(limit)s, and this needs "
                              "%(size)s. Free some space or ask an administrator.", folder=root.get("label") or
                              root.get("name"), free=format_size(free), limit=format_size(limit),
                              size=format_size(max(incoming - max(freed, 0), 0))))


def record(root: dict, delta: int) -> None:
    """Se escribieron (o liberaron, si es negativo) ``delta`` bytes: ajusta el uso guardado sin volver a recorrer
    la carpeta. Si no había nada guardado, se calculará cuando haga falta."""
    with _lock:
        hit = _cache.get(_key(root))
        if hit is not None:
            hit.used = max(hit.used + delta, 0)


def size_of(backend, rel: str) -> int:
    """Lo que ocupa un archivo o una carpeta (para comprobar la cuota antes de copiarla)."""
    entry = backend.stat(rel)
    if entry is None:
        return 0
    if not entry.is_dir:
        return max(int(entry.size or 0), 0)
    return _walk(backend, rel)[0]


def peek(root: dict) -> tuple[int, bool] | None:
    """El uso guardado, sin recorrer nada (las métricas no pueden esperar a un recorrido)."""
    with _lock:
        hit = _cache.get(_key(root))
    return (hit.used, hit.complete) if hit and time.monotonic() - hit.measured < _refresh_seconds * 3 else None


def invalidate(*roots: dict) -> None:
    """Algo cambió en esas carpetas y no se sabe cuánto (borrar una carpeta): se vuelven a medir en segundo plano;
    mientras, vale la medida anterior (por arriba: nunca deja escribir de más)."""
    for root in roots:
        with _lock:
            hit = _cache.get(_key(root))
            if hit is not None:
                hit.stale = True
        if hit is not None:
            _schedule(root)


def clear() -> None:
    with _lock:
        _cache.clear()


def _measure(root: dict, seconds: float = MAX_SECONDS, max_entries: int = MAX_ENTRIES) -> tuple[int, bool]:
    return _walk(root["backend"], "", seconds, max_entries)


def _store(root: dict, used: int, complete: bool) -> None:
    with _lock:
        _cache[_key(root)] = _Usage(time.monotonic(), time.time(), used, complete)


def _schedule(root: dict) -> None:
    """Mide la carpeta en un hilo aparte (una vez a la vez por carpeta)."""
    key = _key(root)
    with _lock:
        if key in _running:
            return
        _running.add(key)

    def work():
        try:
            with _workers:
                used, complete = _measure(root, BACKGROUND_SECONDS, BACKGROUND_ENTRIES)
            _store(root, used, complete)
        except Exception:  # noqa: BLE001 (se reintentará en la siguiente)
            pass
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=work, name=f"storageweb-quota-{root.get('name')}", daemon=True).start()


def measuring(root: dict) -> bool:
    with _lock:
        return _key(root) in _running


def _walk(backend, start: str, seconds: float = MAX_SECONDS, max_entries: int = MAX_ENTRIES) -> tuple[int, bool]:
    total, entries, complete = 0, 0, True
    deadline = time.monotonic() + seconds
    pending = [start]
    while pending:
        if time.monotonic() > deadline or entries >= max_entries:
            complete = False
            break
        rel = pending.pop()
        try:
            items = backend.listdir(rel)
        except (backends.BackendError, OSError):
            continue
        for entry in items:
            entries += 1
            if not backends.is_safe_name(entry.name):
                continue
            if entry.is_dir:
                pending.append(backends.join_rel(rel, entry.name))
            else:
                total += max(int(entry.size or 0), 0)
    return total, complete


def usage(root: dict, *, refresh: bool = False) -> tuple[int, bool]:
    """(bytes usados, si se ha podido contar todo). La medida guardada; si es vieja o dudosa, se vuelve a medir
    en segundo plano y se devuelve la que hay. ``refresh``: medir ya (la tarea ``monitoring``, en su hilo)."""
    with _lock:
        hit = _cache.get(_key(root))
    if hit is not None and not refresh:
        if hit.stale or time.monotonic() - hit.measured >= _refresh_seconds:
            _schedule(root)
        return hit.used, hit.complete
    used, complete = _measure(root, *((BACKGROUND_SECONDS, BACKGROUND_ENTRIES) if refresh else ()))
    _store(root, used, complete)
    return used, complete


def measured_at(root: dict) -> float | None:
    """Cuándo se midió (``time.time()``), o ``None``."""
    with _lock:
        hit = _cache.get(_key(root))
    return hit.at if hit else None


def status(root: dict) -> dict | None:
    """La cuota de una carpeta lista para mostrar, o ``None`` si no tiene:
    ``{used, limit, percent, level (ok|warn|over), used_text, limit_text, complete}``."""
    limit = limit_bytes(root)
    if limit <= 0:
        return None
    used, complete = usage(root)
    percent = round(used * 100 / limit)
    level = "over" if used > limit else "warn" if percent >= _warn_percent else "ok"
    at = measured_at(root)
    return {"used": used, "limit": limit, "percent": percent, "level": level, "complete": complete,
            "used_text": format_size(used), "limit_text": format_size(limit), "measuring": measuring(root),
            "measured_at": iso_from_ts(at) if at else None,
            "measured_text": format_age(time.time() - at) if at else ""}

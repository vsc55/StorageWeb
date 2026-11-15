"""Cuotas de espacio de las carpetas (personales y compartidas). **Solo avisan**: no impiden subir.

La cuota de una carpeta es ``root["quota_mb"]`` (0 = sin cuota): la personal sale del usuario
(``users.quota_mb``) o de ``storage.home_quota_mb``; la compartida, de ``storage.shares[].quota_mb``.

El uso se calcula sumando lo que hay en la carpeta (todo, también lo oculto: ocupa espacio igual) y se guarda en
memoria unos minutos, porque en un almacenamiento remoto recorrerlo es caro. Las escrituras desde la web y por
WebDAV lo invalidan (``invalidate``) para que el aviso salga en cuanto se pasa del límite. Si la carpeta es tan
grande que no da tiempo a recorrerla, el uso es «al menos» lo contado (``complete = False``).
"""
from __future__ import annotations

import threading
import time

from ..i18n import format_size
from . import backends

MB = 1024 * 1024
CACHE_SECONDS = 600
WARN_PERCENT = 90        # a partir de aquí se avisa
MAX_SECONDS = 10.0       # tiempo máximo para recorrer una carpeta
MAX_ENTRIES = 500_000

_cache: dict[str, tuple[float, int, bool]] = {}   # dónde → (cuándo, bytes, completo)
_lock = threading.Lock()


def _key(root: dict) -> str:
    return str(root.get("where") or f"{root.get('location', '')}:{root.get('path')}")


def limit_bytes(root: dict) -> int:
    return int(root.get("quota_mb") or 0) * MB


def invalidate(*roots: dict) -> None:
    """Algo cambió en esas carpetas: el próximo aviso vuelve a calcular su uso."""
    with _lock:
        for root in roots:
            _cache.pop(_key(root), None)


def clear() -> None:
    with _lock:
        _cache.clear()


def _measure(root: dict) -> tuple[int, bool]:
    backend = root["backend"]
    total, entries, complete = 0, 0, True
    deadline = time.monotonic() + MAX_SECONDS
    pending = [""]
    while pending:
        if time.monotonic() > deadline or entries >= MAX_ENTRIES:
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
    """(bytes usados, si se ha podido contar todo). De la caché si es reciente."""
    key = _key(root)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
    if hit and not refresh and now - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2]
    used, complete = _measure(root)
    with _lock:
        _cache[key] = (time.monotonic(), used, complete)
    return used, complete


def status(root: dict) -> dict | None:
    """La cuota de una carpeta lista para mostrar, o ``None`` si no tiene:
    ``{used, limit, percent, level (ok|warn|over), used_text, limit_text, complete}``."""
    limit = limit_bytes(root)
    if limit <= 0:
        return None
    used, complete = usage(root)
    percent = round(used * 100 / limit)
    level = "over" if used > limit else "warn" if percent >= WARN_PERCENT else "ok"
    return {"used": used, "limit": limit, "percent": percent, "level": level, "complete": complete,
            "used_text": format_size(used), "limit_text": format_size(limit)}

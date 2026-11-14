"""Avisos para los administradores: lo que necesita atención (Resumen y globo de la barra lateral).

Cada módulo de ``core`` aporta los suyos con el decorador :func:`source` (las copias en
``maintenance``, las carpetas en ``shares``, la red en ``network``, los métodos de inicio de sesión en
``auth``, que pregunta a cada proveedor); :func:`collect` los reúne sin saber de qué tratan.

Cada aviso dice en qué página se resuelve (``page``, una clave de ``web/nav.py``) para que la web
pueda enlazarlo. ``level`` es ``danger``, ``warn`` o ``info``; los ``info`` no cuentan en el globo.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .. import registry
from ..i18n import _, ngettext

LEVELS = {"danger": 0, "warn": 1, "info": 2}


@dataclass(frozen=True)
class Context:
    """Lo que necesitan las fuentes de avisos.

    ``cfg`` son los ajustes efectivos, ``boot`` los de arranque, ``maint_state`` lo que guarda
    ``maintenance.state`` (cuándo se intentó cada tarea), ``locked`` los campos fijados fuera de la
    web (``RuntimeSettings.locked()``) y ``network`` el diagnóstico de la petición (``core.network``).
    """
    cfg: dict
    boot: dict
    maint_state: dict
    locked: dict
    network: dict | None


Source = Callable[[Context], Iterable[dict]]
_SOURCES: list[tuple[int, str, Source]] = []


def source(name: str, order: int = 50) -> Callable[[Source], Source]:
    """Registra una función que devuelve avisos (``alert(...)``) a partir del :class:`Context`."""
    def decorate(fn: Source) -> Source:
        if all(existing != name for _o, existing, _f in _SOURCES):
            _SOURCES.append((order, name, fn))
            _SOURCES.sort(key=lambda item: (item[0], item[1]))
        return fn
    return decorate


def alert(level: str, key: str, title: str, detail: str, page: str, action: str, anchor: str = "") -> dict:
    if level not in LEVELS:
        raise ValueError(level)
    return {"level": level, "key": key, "title": title, "detail": detail, "page": page, "action": action,
            "anchor": anchor}


def collect(cfg: dict, boot: dict, maint_state: dict, locked: dict | None = None,
            network: dict | None = None) -> list[dict]:
    """Avisos actuales, del más grave al menos."""
    registry.import_submodules("storageweb.core")  # las fuentes se registran al importar su módulo
    ctx = Context(cfg, boot, maint_state, locked or {}, network)
    alerts: list[dict] = []
    for _order, _name, fn in _SOURCES:
        alerts.extend(fn(ctx))
    return sorted(alerts, key=lambda a: LEVELS[a["level"]])


def count(alerts: list[dict]) -> int:
    return sum(1 for a in alerts if a["level"] != "info")


@source("locked", order=90)
def _locked(ctx: Context):
    """Ajustes fijados en config.json o en el entorno (no se pueden cambiar desde la web)."""
    if not ctx.locked:
        return []
    files = sum(1 for origin in ctx.locked.values() if origin == "file")
    envs = len(ctx.locked) - files
    parts = []
    if files:
        parts.append(ngettext("%(num)s in config.json", "%(num)s in config.json", files))
    if envs:
        parts.append(ngettext("%(num)s in environment variables", "%(num)s in environment variables", envs))
    return [alert("info", "locked", ngettext("%(num)s setting is locked", "%(num)s settings are locked",
                                             len(ctx.locked)),
                  " · ".join(parts), "system", _("See which ones"), "layers-title")]

"""Combinar las capas de configuración campo a campo y recorrer sus campos por ruta.

Una «ruta» es el nombre de un campo con puntos (``auth.entra.client_id``). Las listas y los
diccionarios de ``LEAF_PATHS`` (``role_mappings``) cuentan como un único campo.
"""
from __future__ import annotations

import copy

from .defaults import LEAF_PATHS, RUNTIME_SECTIONS


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def merge_overrides(base: dict, override: dict, path: tuple = ()) -> dict:
    """Combina ajustes web sobre ``base`` campo a campo (salvo los ``LEAF_PATHS``)."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        here = path + (key,)
        if isinstance(value, dict) and isinstance(out.get(key), dict) and here not in LEAF_PATHS:
            out[key] = merge_overrides(out[key], value, here)
        else:
            out[key] = copy.deepcopy(value)
    return out


def diff_overrides(base: dict, new: dict, path: tuple = ()) -> dict:
    """Lo mínimo que hay que guardar para que ``new`` resulte de combinarlo sobre ``base``."""
    out = {}
    for key, value in new.items():
        here = path + (key,)
        old = base.get(key) if isinstance(base, dict) else None
        if isinstance(value, dict) and isinstance(old, dict) and here not in LEAF_PATHS:
            sub = diff_overrides(old, value, here)
            if sub:
                out[key] = sub
        elif value != old:
            out[key] = copy.deepcopy(value)
    return out


def leaf_paths(tree: dict, path: tuple = ()) -> set[str]:
    """Rutas ("auth.entra.tenant_id") de los valores de un árbol de ajustes."""
    paths = set()
    for key, value in tree.items():
        here = path + (key,)
        if isinstance(value, dict) and here not in LEAF_PATHS:
            paths |= leaf_paths(value, here)  # un diccionario vacío no aporta ningún campo
        else:
            paths.add(".".join(here))
    return paths


def drop_path(tree: dict, dotted: str) -> dict:
    """Copia de ``tree`` sin la ruta indicada (y sin los diccionarios que queden vacíos)."""
    out = copy.deepcopy(tree)
    keys = dotted.split(".")
    stack = [out]
    for key in keys[:-1]:
        node = stack[-1].get(key)
        if not isinstance(node, dict):
            return out
        stack.append(node)
    stack[-1].pop(keys[-1], None)
    for i in range(len(keys) - 2, -1, -1):
        if not stack[i + 1]:
            stack[i].pop(keys[i], None)
    return out


def get_path(tree: dict, dotted: str):
    """Valor de un campo por su ruta (``auth.entra.client_id``), o ``None`` si no existe."""
    value = tree
    for key in dotted.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _get(d: dict, path: tuple):
    for key in path:
        d = d.get(key, {}) if isinstance(d, dict) else {}
    return d


def _set(d: dict, path: tuple, value) -> None:
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def runtime_part(tree: dict) -> dict:
    """Solo las secciones editables desde la web de un árbol de ajustes (sin validar)."""
    return {k: copy.deepcopy(v) for k, v in tree.items() if k in RUNTIME_SECTIONS}


def runtime_view(cfg: dict) -> dict:
    """Extrae las secciones editables desde la web."""
    return {k: copy.deepcopy(cfg[k]) for k in RUNTIME_SECTIONS}

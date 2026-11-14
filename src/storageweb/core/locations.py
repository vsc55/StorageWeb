"""Ubicaciones de almacenamiento (``storage.locations``): alta, cambios, borrado y prueba de conexión.

Una ubicación es una conexión con nombre a un almacenamiento externo; las carpetas compartidas y las
personales la eligen con ``location``. El nombre no cambia una vez creada (las carpetas lo usan).

Nada aquí depende del tipo: sus opciones están en su ``schema`` (``settings.location_types``), que
declara su backend en ``core/backends/<tipo>.py``.
"""
from __future__ import annotations

import copy
from pathlib import Path

from ..i18n import _
from ..settings import location_types
from ..settings.location_types import LocationSchema
from . import backends


class LocationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def find(locations: list[dict], name: str) -> dict | None:
    return next((loc for loc in locations if loc["name"] == name), None)


def schema(kind: str) -> LocationSchema:
    found = location_types.get(kind)
    if found is None:
        raise LocationError(_("Unknown storage type: %(type)s", type=kind))
    return found


def schemas() -> list[LocationSchema]:
    return location_types.all_schemas()


def blank(kind: str) -> dict:
    return schema(kind).blank()


def from_form(form: dict, original: dict | None) -> dict:
    """La ubicación del formulario (sin validar: lo hace el cargador). Un secreto vacío conserva el anterior."""
    kind = original["type"] if original else str(form.get("type", ""))
    loc = blank(kind)
    loc["name"] = original["name"] if original else str(form.get("name", "")).strip()
    loc["label"] = str(form.get("label", "")).strip()
    for option in schema(kind).options:
        if option.kind == "bool":
            loc[option.name] = form.get(option.name) == "on"
        else:
            loc[option.name] = str(form.get(option.name, "")).strip()
        if option.secret and not loc[option.name] and original:
            loc[option.name] = original.get(option.name, "")
    return loc


def replace(locations: list[dict], original: str | None, loc: dict) -> list[dict]:
    result = copy.deepcopy(locations)
    if original is None:
        if find(result, loc["name"]) is not None:
            raise LocationError(_("Duplicate storage location name: %(name)s", name=repr(loc["name"])))
        return result + [loc]
    for i, current in enumerate(result):
        if current["name"] == original:
            result[i] = loc
            return result
    raise LocationError(_("The storage location %(name)s does not exist.", name=original))


def users_of(cfg: dict, name: str) -> list[str]:
    """Qué la usa: etiquetas de las carpetas compartidas y «Carpetas personales»."""
    used = [s["label"] or s["name"] for s in cfg["storage"]["shares"] if s.get("location") == name]
    if cfg["storage"].get("home_location") == name:
        used.insert(0, str(_("Personal folders")))
    return used


def remove(cfg: dict, name: str) -> list[dict]:
    used = users_of(cfg, name)
    if used:
        raise LocationError(_("It is in use by: %(names)s. Move those folders to another location first.",
                              names=", ".join(used)))
    return [copy.deepcopy(loc) for loc in cfg["storage"]["locations"] if loc["name"] != name]


def describe(loc: dict, path: str = "") -> str:
    """Dirección legible de ``path`` en la ubicación; la da su tipo (``s3://…``, ruta UNC…)."""
    try:
        return backends.address(loc, path)
    except backends.BackendError:
        return f"{loc.get('type')}://{loc.get('name')}/{path}".rstrip("/")


def where(cfg: dict, location: str, path: str) -> str:
    """Dónde está una carpeta, para mostrarlo en la administración."""
    if not location:
        return path
    loc = find(cfg["storage"].get("locations", []), location)
    return describe(loc, path) if loc else f"{location}:/{path}"


def local_exists(location: str, path: str) -> bool | None:
    """Si la carpeta existe en el disco del servidor; ``None`` si está en una ubicación remota."""
    if location:
        return None
    return bool(path) and Path(path).exists()


def test(cfg: dict, loc: dict) -> str | None:
    """Comprueba la conexión y el acceso. Devuelve el error o ``None`` si todo va bien."""
    try:
        backends.backend_for(loc, "", backends.staging_dir(cfg)).check()
    except backends.BackendError as exc:
        return exc.message
    except Exception as exc:  # noqa: BLE001 (red, DNS, certificados…: se muestra tal cual)
        return str(exc) or exc.__class__.__name__
    return None

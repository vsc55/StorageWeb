"""Esquema de los tipos de ubicación de almacenamiento (S3, SMB…): qué opciones tiene cada uno.

Cada tipo lo declara su backend en ``core/backends/<tipo>.py`` (``schema = LocationSchema(...)``) y
``core.backends.discover()`` lo registra aquí. El cargador de ajustes, las páginas de la administración
y la referencia generada solo leen este registro: un tipo nuevo es un fichero nuevo, sin tocar código
general.

Este módulo solo describe datos y los valida; no importa nada de ``core`` (capas: settings es la base).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..i18n import _
from .errors import ConfigError

# Clases de opción: cómo se valida y qué control muestra la web
# server_path: ruta en un servidor (SFTP, FTP): absoluta (/srv/datos) o relativa a la carpeta del usuario
OPTION_KINDS = ("text", "path", "server_path", "url", "secret", "bool", "port", "multiline")


@dataclass(frozen=True)
class Option:
    name: str
    label: object                 # etiqueta en la web (traducible)
    doc: str                      # descripción para la referencia generada (en español)
    kind: str = "text"            # ver OPTION_KINDS
    required: bool = False
    default: object = None        # None = vacío ("" o False según la clase)
    help: object = ""             # ayuda bajo el campo en la web
    placeholder: str = ""
    section: str = "place"        # place (dónde) | credentials

    def __post_init__(self):
        if self.kind not in OPTION_KINDS:
            raise ValueError(f"Unknown option kind: {self.kind}")

    @property
    def empty(self):
        if self.default is not None:
            return self.default
        return False if self.kind == "bool" else ""

    @property
    def secret(self) -> bool:
        """Secretos: nunca se muestran; vacío al editar = se conserva. ``multiline`` (claves privadas) también."""
        return self.kind in ("secret", "multiline")

    def normalize(self, value, where: str):
        """Valor validado; :class:`ConfigError` con ``where`` (``Ubicación 'x'``) si no vale."""
        if value is None or value == "":
            value = self.empty
        if self.kind == "bool":
            return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
        if self.kind == "port":
            try:
                port = int(value)
            except (TypeError, ValueError):
                port = 0
            if not 1 <= port <= 65535:
                raise ConfigError(_("%(where)s: %(field)s must be a port number (1-65535)", where=where,
                                    field=self.name), "storage.locations")
            return port
        text = str(value).strip()
        if self.kind in ("path", "server_path"):
            parts = [p for p in text.replace("\\", "/").split("/") if p not in ("", ".")]
            absolute = self.kind == "server_path" and text.startswith(("/", "\\"))
            if ".." in parts or (parts and ":" in parts[0]):
                message = (_("%(where)s: %(field)s must be a relative path", where=where, field=self.name)
                           if self.kind == "path" else
                           _("%(where)s: %(field)s cannot contain «..»", where=where, field=self.name))
                raise ConfigError(message, "storage.locations")
            text = ("/" if absolute else "") + "/".join(parts)
        if self.kind == "url" and text and not text.startswith(("http://", "https://")):
            raise ConfigError(_("%(where)s: %(field)s must start with https://", where=where, field=self.name),
                              "storage.locations")
        if self.required and not text:
            raise ConfigError(_("%(where)s: %(field)s is required", where=where, field=self.name),
                              "storage.locations")
        return text


@dataclass(frozen=True)
class LocationSchema:
    kind: str                     # valor de ``type`` en la configuración
    label: object                 # «S3 (Amazon, MinIO…)»
    short_label: str              # «S3»: botones, insignias
    doc: str                      # una línea para la referencia generada
    place_title: object           # título de la sección «dónde» del formulario («Bucket», «Recurso»)
    options: tuple[Option, ...]
    credentials_help: object = ""
    label_placeholder: object = ""
    name_placeholder: str = ""
    extra: str = ""               # dependencia opcional de pip (``storageweb[<extra>]``)
    _by_name: dict = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_by_name", {o.name: o for o in self.options})

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(o.name for o in self.options if o.secret)

    def sections(self) -> list[tuple[str, list[Option]]]:
        """Opciones agrupadas por sección, en el orden en que aparecen."""
        groups: dict[str, list[Option]] = {}
        for option in self.options:
            groups.setdefault(option.section, []).append(option)
        return list(groups.items())

    def blank(self) -> dict:
        return {"name": "", "label": "", "type": self.kind, **{o.name: o.empty for o in self.options}}

    def normalize(self, item: dict, name: str) -> dict:
        where = _("Storage location %(name)s", name=repr(name))
        loc = {"name": name, "label": str(item.get("label") or name).strip(), "type": self.kind}
        for option in self.options:
            loc[option.name] = option.normalize(item.get(option.name), where)
        return loc


_SCHEMAS: dict[str, LocationSchema] = {}


def register(schema: LocationSchema) -> None:
    current = _SCHEMAS.get(schema.kind)
    if current is not None and current is not schema:
        raise ValueError(f"Storage type {schema.kind!r} registered twice")
    _SCHEMAS[schema.kind] = schema


def get(kind: str) -> LocationSchema | None:
    return _SCHEMAS.get(kind)


def all_schemas() -> list[LocationSchema]:
    return list(_SCHEMAS.values())


def kinds() -> list[str]:
    return list(_SCHEMAS)

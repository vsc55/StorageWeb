"""Lectura, combinación y validación de la configuración.

Capas, de menor a mayor prioridad (cada una gana campo a campo sobre las anteriores):

    DEFAULTS  <  ajustes web (SQLite, solo RUNTIME_SECTIONS)  <  config.json  <  variables de entorno

Un campo fijado en config.json o en el entorno queda **bloqueado**: la web lo muestra pero no lo
puede cambiar. Combinar capas: ``layers.py``; variables de entorno: ``env.py``.
"""
from __future__ import annotations

import copy
import json
import os
import re
import urllib.parse
import secrets
import sys
from pathlib import Path

from .. import patterns
from ..i18n import LOCALES, _
from .env import env_config
from .errors import ConfigError
from .layers import _get, _set, merge_overrides
from . import location_types
from . import auth_methods
from .defaults import DEFAULTS, PERMISSIONS, RUNTIME_SECTIONS, SECRET_FIELDS

SHARE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROFILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def default_config_path() -> Path:
    env = os.environ.get("STORAGEWEB_CONFIG")
    if env:
        return Path(env)
    if sys.platform != "win32":
        system = Path("/etc/storageweb/config.json")
        if system.exists():
            return system
    return Path.cwd() / "config" / "config.json"


def read_config_file(path: str | os.PathLike | None = None) -> tuple[dict, Path]:
    cfg_path = Path(path) if path else default_config_path()
    data: dict = {}
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ConfigError(_("Invalid JSON in %(path)s: %(error)s", path=cfg_path, error=exc)) from exc
        if not isinstance(data, dict):
            raise ConfigError(_("%(path)s must contain a JSON object", path=cfg_path))
    return data, cfg_path


def _apply_overrides(cfg: dict, overrides: dict) -> dict:
    """Aplica los ajustes web (solo las secciones editables) campo a campo."""
    for section in RUNTIME_SECTIONS:
        if section not in overrides:
            continue
        value = overrides[section]
        if isinstance(DEFAULTS.get(section), dict):
            if not isinstance(value, dict):
                raise ConfigError(_("Setting %(section)s must be an object", section=section))
            cfg[section] = merge_overrides(cfg[section], value, (section,))
        else:
            cfg[section] = value
    return cfg


def _resolve(base_dir: Path, value: str) -> Path:
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else (base_dir / p)


def _field_path(field: str) -> str | None:
    """Ruta completa del ajuste a partir del nombre que usan los mensajes («storage.shares»)."""
    if field.startswith(("storage.", "security.", "auth.", "network.", "server.", "maintenance.", "branding.")):
        return field
    return "storage.shares" if "." in field else None


_HOST_RE = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
                      r"|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$")


def _public_url(value) -> str:
    """Dirección pública normalizada a ``https://fqdn[:puerto][/ruta]`` (sin barra final), o vacío.

    Basta con el FQDN (``files.empresa.es``, ``files.empresa.es/archivos``): se asume HTTPS. Solo si
    se escribe ``http://`` explícitamente se usa HTTP (pruebas en local).
    """
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parts = urllib.parse.urlsplit(value)
    if (parts.scheme not in ("http", "https") or not _HOST_RE.match(parts.netloc or "")
            or parts.query or parts.fragment or " " in parts.path):
        raise ConfigError(_("network.public_url must be a host name like files.example.com (optionally with "
                            "a port or a path, no query)"), "network.public_url")
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path}"


def _inside_location(value: str, field: str) -> str:
    """Ruta relativa dentro de una ubicación (``a/b``): ni ``..`` ni rutas absolutas o con unidad."""
    parts = [p for p in str(value or "").strip().replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts or (parts and ":" in parts[0]):
        raise ConfigError(_("%(field)s: inside a storage location the path must be relative (for example "
                            "folders/accounting)", field=field), _field_path(field))
    return "/".join(parts)


def _locations(items) -> list[dict]:
    """Valida y normaliza ``storage.locations``: lo común aquí; las opciones, con el esquema de su tipo."""
    if not isinstance(items, list):
        raise ConfigError(_("storage.locations must be a list"), "storage.locations")
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ConfigError(_("storage.locations must be a list of objects"), "storage.locations")
        name = str(item.get("name", "")).strip()
        if not SHARE_NAME_RE.match(name):
            raise ConfigError(_("Invalid storage location name %(name)s (letters, digits, _ and -)", name=repr(name)),
                              "storage.locations")
        if name.lower() in seen:
            raise ConfigError(_("Duplicate storage location name: %(name)s", name=repr(name)), "storage.locations")
        seen.add(name.lower())
        kind = str(item.get("type", "")).strip().lower()
        schema = location_types.get(kind)
        if schema is None:  # los tipos los declara cada backend (core/backends)
            raise ConfigError(_("Storage location %(name)s: the type must be one of: %(values)s", name=repr(name),
                                values=", ".join(location_types.kinds())), "storage.locations")
        loc = schema.normalize(item, name)
        result.append(loc)
    return result


def _str_list(value, field: str) -> list[str]:
    if isinstance(value, str):
        value = [x for x in re.split(r"[,\s]+", value) if x]
    if not isinstance(value, list):
        raise ConfigError(_("%(field)s must be a list", field=field), _field_path(field))
    return [str(x).strip() for x in value if str(x).strip()]


def _non_negative_int(value, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(_("%(field)s must be an integer", field=field), _field_path(field)) from exc
    if number < 0:
        raise ConfigError(_("%(field)s cannot be negative", field=field), _field_path(field))
    return number


def _positive_int(value, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(_("%(field)s must be an integer", field=field), _field_path(field)) from exc
    if number < 1:
        raise ConfigError(_("%(field)s must be greater than 0", field=field), _field_path(field))
    return number


def normalize(file_cfg: dict, cfg_path: Path, overrides: dict | None = None, env_cfg: dict | None = None) -> dict:
    """Combina DEFAULTS < ajustes web < config.json < entorno, resuelve rutas y valida."""
    cfg = copy.deepcopy(DEFAULTS)
    if overrides:
        cfg = _apply_overrides(cfg, overrides)
    cfg = merge_overrides(cfg, file_cfg)
    if env_cfg:
        cfg = merge_overrides(cfg, env_cfg)
    base_dir = cfg_path.resolve().parent
    cfg["_config_path"] = str(cfg_path)

    # --- rutas (las relativas se resuelven respecto al directorio del config.json)
    cfg["server"]["max_upload_mb"] = _positive_int(cfg["server"]["max_upload_mb"], "server.max_upload_mb")
    data_dir = _resolve(base_dir, cfg["data_dir"])
    cfg["data_dir"] = str(data_dir)
    cfg["database"] = str(_resolve(base_dir, cfg.get("database") or str(data_dir / "storageweb.db")))

    storage = cfg["storage"]
    storage["locations"] = _locations(storage.get("locations", []))
    location_names = {loc["name"] for loc in storage["locations"]}
    storage["home_location"] = str(storage.get("home_location") or "").strip()
    if storage["home_location"] and storage["home_location"] not in location_names:
        raise ConfigError(_("storage.home_location: there is no storage location named %(name)s",
                            name=repr(storage["home_location"])), "storage.home_location")
    tmpl = str(storage["home_template"]).strip()
    if "{username}" not in tmpl:
        raise ConfigError(_("storage.home_template must contain {username}"), "storage.home_template")
    if storage["home_location"]:
        tmpl = _inside_location(tmpl, "storage.home_template")
    else:
        if not Path(os.path.expanduser(tmpl.split("{username}")[0] or ".")).is_absolute():
            tmpl = str(base_dir / tmpl)
        tmpl = os.path.expanduser(tmpl)
    storage["home_template"] = tmpl
    for key in ("create_home", "create_shares", "show_hidden"):
        storage[key] = bool(storage[key])
    try:
        storage["hidden"] = patterns.normalize(_str_list(storage.get("hidden") or [], "storage.hidden"))
    except patterns.PatternError as exc:
        raise ConfigError(str(exc), "storage.hidden") from exc
    storage["max_file_size_mb"] = _non_negative_int(storage["max_file_size_mb"], "storage.max_file_size_mb")
    storage["home_quota_mb"] = _non_negative_int(storage.get("home_quota_mb", 0), "storage.home_quota_mb")

    seen = {"home"}
    shares = []
    for share in storage["shares"]:
        name = str(share.get("name", "")).strip()
        if not SHARE_NAME_RE.match(name):
            raise ConfigError(_("Invalid shared folder name %(name)s (letters, digits, _ and -)", name=repr(name)), "storage.shares")
        if name.lower() in seen:
            raise ConfigError(_("Duplicate or reserved shared folder name: %(name)s", name=repr(name)), "storage.shares")
        seen.add(name.lower())
        location = str(share.get("location") or "").strip()
        if location and location not in location_names:
            raise ConfigError(_("Shared folder %(name)s uses the storage location %(location)s, which does not exist",
                                name=repr(name), location=repr(location)), "storage.shares")
        if not share.get("path") and not location:
            raise ConfigError(_("Shared folder %(name)s has no path", name=repr(name)), "storage.shares")
        raw_path = str(share.get("path") or "").strip()
        shares.append({
            "name": name,
            "label": str(share.get("label") or name).strip(),
            "location": location,
            # En el disco: ruta absoluta (las relativas, respecto al config.json). En una ubicación: ruta dentro de ella
            "path": _inside_location(raw_path, "storage.shares") if location else str(_resolve(base_dir, raw_path)),
            "read_only": bool(share.get("read_only", False)),
            "quota_mb": _non_negative_int(share.get("quota_mb", 0) or 0, "storage.shares"),
            "users": [u.lower() for u in _str_list(share.get("users", ["*"]), f"{name}.users")],
            "read_only_users": [u.lower() for u in _str_list(share.get("read_only_users", []),
                                                             f"{name}.read_only_users")],
            "groups": [g.lower() for g in _str_list(share.get("groups", []), f"{name}.groups")],
            "read_only_groups": [g.lower() for g in _str_list(share.get("read_only_groups", []),
                                                              f"{name}.read_only_groups")],
        })
    storage["shares"] = shares

    # --- permisos
    user_perms = cfg["permissions"].get("user") or {}
    cfg["permissions"] = {"user": {p: bool(user_perms.get(p, False)) for p in PERMISSIONS}}

    # --- autenticación: cada método valida su apartado (lo declara su proveedor)
    for conf in auth_methods.configs():
        section = cfg["auth"][conf.key]
        section["enabled"] = bool(section["enabled"])
        conf.validate(section, cfg)
    if not any(cfg["auth"][conf.key]["enabled"] for conf in auth_methods.configs()):
        raise ConfigError(_("At least one sign-in method must be enabled"), "auth")

    # --- red
    net = cfg["network"]
    net["public_url"] = _public_url(net.get("public_url"))
    cfg["server"]["proxy_hops"] = _positive_int(cfg["server"].get("proxy_hops", 1), "server.proxy_hops")

    # --- seguridad
    sec = cfg["security"]
    sec["max_login_failures"] = _positive_int(sec["max_login_failures"], "security.max_login_failures")
    sec["lockout_minutes"] = _positive_int(sec["lockout_minutes"], "security.lockout_minutes")
    sec["ipban_enabled"] = bool(sec["ipban_enabled"])
    sec["ipban_threshold"] = _positive_int(sec["ipban_threshold"], "security.ipban_threshold")
    sec["ipban_window_minutes"] = _positive_int(sec["ipban_window_minutes"], "security.ipban_window_minutes")
    sec["ipban_minutes"] = _non_negative_int(sec["ipban_minutes"], "security.ipban_minutes")
    sec["api_tokens"] = bool(sec["api_tokens"])
    sec["webdav"] = bool(sec["webdav"])
    sec["webdav_passwords"] = bool(sec["webdav_passwords"])

    # --- mantenimiento
    maint = cfg["maintenance"]
    maint["audit_retention_days"] = _non_negative_int(maint["audit_retention_days"], "maintenance.audit_retention_days")
    maint["backup_interval_hours"] = _non_negative_int(maint["backup_interval_hours"],
                                                       "maintenance.backup_interval_hours")
    maint["backup_keep"] = _positive_int(maint["backup_keep"], "maintenance.backup_keep")

    # --- marca
    brand = cfg["branding"]
    brand["primary_color"] = str(brand.get("primary_color") or "").strip().lower()
    if brand["primary_color"] and not re.match(r"^#[0-9a-f]{6}$", brand["primary_color"]):
        raise ConfigError(_("branding.primary_color must be a color like #2563eb"), "branding.primary_color")
    brand["logo"] = str(brand.get("logo") or "").strip()
    if brand["logo"] and not re.match(r"^logo\.(png|jpg|jpeg|webp|svg)$", brand["logo"]):
        raise ConfigError(_("branding.logo is not valid"), "branding.logo")
    cfg["settings_profile"] = str(cfg["settings_profile"] or "default").strip()
    if not PROFILE_RE.match(cfg["settings_profile"]):
        raise ConfigError(_("settings_profile can only contain letters, digits, _ and -"), "settings_profile")
    cfg["app_name"] = str(cfg["app_name"]).strip() or DEFAULTS["app_name"]
    if cfg["default_locale"] not in LOCALES:
        raise ConfigError(_("default_locale must be one of: %(values)s", values=", ".join(LOCALES)), "default_locale")
    return cfg


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None, environ=None) -> dict:
    """Configuración efectiva: config.json + variables de entorno (+ ajustes web si se pasan)."""
    file_cfg, cfg_path = read_config_file(path)
    return normalize(file_cfg, cfg_path, overrides, env_config(environ))


def ensure_secret_key(cfg: dict) -> str:
    if cfg.get("secret_key"):
        return cfg["secret_key"]
    data_dir = Path(cfg["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


def mask_secrets(cfg: dict) -> dict:
    out = copy.deepcopy(cfg)
    for path in SECRET_FIELDS:
        if _get(out, path):
            _set(out, path, "********")
    for loc in out.get("storage", {}).get("locations", []):
        schema = location_types.get(loc.get("type", ""))
        for field in schema.secrets if schema else ():
            if loc.get(field):
                loc[field] = "********"
    return out



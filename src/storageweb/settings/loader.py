"""Lectura, combinación y validación de la configuración.

Orden de prioridad (de menor a mayor):
    DEFAULTS  <  config.json  <  ajustes guardados desde la web (solo RUNTIME_SECTIONS)
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import sys
from pathlib import Path

from ..i18n import LOCALES, _
from .defaults import (DEFAULTS, PERMISSIONS, ROLES, RUNTIME_SECTIONS, SECRET_FIELDS,
                       SSO_PROVIDER_NAMES)

SHARE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ConfigError(Exception):
    pass


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


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


def _get(d: dict, path: tuple):
    for key in path:
        d = d.get(key, {}) if isinstance(d, dict) else {}
    return d


def _set(d: dict, path: tuple, value) -> None:
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def _apply_overrides(cfg: dict, file_cfg: dict, overrides: dict) -> dict:
    for section in RUNTIME_SECTIONS:
        if section not in overrides:
            continue
        value = overrides[section]
        if isinstance(DEFAULTS.get(section), dict):
            if not isinstance(value, dict):
                raise ConfigError(_("Setting %(section)s must be an object", section=section))
            cfg[section] = deep_merge(DEFAULTS[section], value)
        else:
            cfg[section] = value
    # Un secreto vacío en los ajustes web significa "usar el de config.json"
    for path in SECRET_FIELDS:
        if path[0] in overrides and not _get(cfg, path):
            file_value = _get(file_cfg, path)
            if file_value:
                _set(cfg, path, file_value)
    return cfg


def _resolve(base_dir: Path, value: str) -> Path:
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else (base_dir / p)


def _str_list(value, field: str) -> list[str]:
    if isinstance(value, str):
        value = [x for x in re.split(r"[,\s]+", value) if x]
    if not isinstance(value, list):
        raise ConfigError(_("%(field)s must be a list", field=field))
    return [str(x).strip() for x in value if str(x).strip()]


def _non_negative_int(value, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(_("%(field)s must be an integer", field=field)) from exc
    if number < 0:
        raise ConfigError(_("%(field)s cannot be negative", field=field))
    return number


def _positive_int(value, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(_("%(field)s must be an integer", field=field)) from exc
    if number < 1:
        raise ConfigError(_("%(field)s must be greater than 0", field=field))
    return number


def normalize(file_cfg: dict, cfg_path: Path, overrides: dict | None = None) -> dict:
    """Combina DEFAULTS + config.json + ajustes web, resuelve rutas y valida."""
    cfg = deep_merge(DEFAULTS, file_cfg)
    if overrides:
        cfg = _apply_overrides(cfg, file_cfg, overrides)
    base_dir = cfg_path.resolve().parent
    cfg["_config_path"] = str(cfg_path)

    # --- rutas (las relativas se resuelven respecto al directorio del config.json)
    cfg["server"]["max_upload_mb"] = _positive_int(cfg["server"]["max_upload_mb"], "server.max_upload_mb")
    data_dir = _resolve(base_dir, cfg["data_dir"])
    cfg["data_dir"] = str(data_dir)
    cfg["database"] = str(_resolve(base_dir, cfg.get("database") or str(data_dir / "storageweb.db")))

    storage = cfg["storage"]
    tmpl = str(storage["home_template"]).strip()
    if "{username}" not in tmpl:
        raise ConfigError(_("storage.home_template must contain {username}"))
    if not Path(os.path.expanduser(tmpl.split("{username}")[0] or ".")).is_absolute():
        tmpl = str(base_dir / tmpl)
    storage["home_template"] = os.path.expanduser(tmpl)
    for key in ("create_home", "create_shares", "show_hidden"):
        storage[key] = bool(storage[key])
    storage["max_file_size_mb"] = _non_negative_int(storage["max_file_size_mb"], "storage.max_file_size_mb")

    seen = {"home"}
    shares = []
    for share in storage["shares"]:
        name = str(share.get("name", "")).strip()
        if not SHARE_NAME_RE.match(name):
            raise ConfigError(_("Invalid shared folder name %(name)s (letters, digits, _ and -)", name=repr(name)))
        if name.lower() in seen:
            raise ConfigError(_("Duplicate or reserved shared folder name: %(name)s", name=repr(name)))
        seen.add(name.lower())
        if not share.get("path"):
            raise ConfigError(_("Shared folder %(name)s has no path", name=repr(name)))
        shares.append({
            "name": name,
            "label": str(share.get("label") or name).strip(),
            "path": str(_resolve(base_dir, str(share["path"]).strip())),
            "read_only": bool(share.get("read_only", False)),
            "users": [u.lower() for u in _str_list(share.get("users", ["*"]), f"{name}.users")],
            "groups": [g.lower() for g in _str_list(share.get("groups", []), f"{name}.groups")],
        })
    storage["shares"] = shares

    # --- permisos
    user_perms = cfg["permissions"].get("user") or {}
    cfg["permissions"] = {"user": {p: bool(user_perms.get(p, False)) for p in PERMISSIONS}}

    # --- autenticación
    pam = cfg["auth"]["pam"]
    pam["enabled"] = bool(pam["enabled"])
    pam["allowed_groups"] = [g.lower() for g in _str_list(pam["allowed_groups"], "pam.allowed_groups")]
    pam["admin_groups"] = [g.lower() for g in _str_list(pam["admin_groups"], "pam.admin_groups")]
    if pam["enabled"] and sys.platform == "win32":
        raise ConfigError(_("auth.pam is not available on Windows"))

    entra = cfg["auth"]["entra"]
    entra["enabled"] = bool(entra["enabled"])
    if entra["provider"] not in SSO_PROVIDER_NAMES:
        raise ConfigError(_("auth.entra.provider must be one of: %(values)s", values=", ".join(SSO_PROVIDER_NAMES)))
    entra["scopes"] = _str_list(entra["scopes"], "entra.scopes")
    entra["allowed_groups"] = _str_list(entra["allowed_groups"], "entra.allowed_groups")
    if entra["default_role"] not in ROLES:
        raise ConfigError(_("auth.entra.default_role must be one of: %(values)s", values=", ".join(ROLES)))
    if not isinstance(entra["role_mappings"], dict):
        raise ConfigError(_("auth.entra.role_mappings must be an object {group: role}"))
    mappings = {}
    for key, role in entra["role_mappings"].items():
        if role not in ROLES:
            raise ConfigError(_("Invalid role %(role)s in role_mappings (use %(values)s)", role=repr(role), values=", ".join(ROLES)))
        mappings[str(key).strip().lower()] = role
    entra["role_mappings"] = mappings
    entra["timeout_seconds"] = _positive_int(entra["timeout_seconds"], "entra.timeout_seconds")
    if entra["enabled"]:
        required = ["client_id", "client_secret"]
        custom_endpoints = all(entra.get(k) for k in ("authorize_url", "token_url", "issuer"))
        if entra["provider"] == "msal" or not custom_endpoints:
            required.append("tenant_id")
        missing = [k for k in required if not entra.get(k)]
        if missing:
            raise ConfigError(_("Entra ID is enabled but these are missing: %(fields)s", fields=", ".join(missing)))

    cfg["auth"]["local"]["enabled"] = bool(cfg["auth"]["local"]["enabled"])
    if not (cfg["auth"]["local"]["enabled"] or pam["enabled"] or entra["enabled"]):
        raise ConfigError(_("At least one sign-in method must be enabled"))

    # --- seguridad
    sec = cfg["security"]
    sec["max_login_failures"] = _positive_int(sec["max_login_failures"], "security.max_login_failures")
    sec["lockout_minutes"] = _positive_int(sec["lockout_minutes"], "security.lockout_minutes")
    cfg["app_name"] = str(cfg["app_name"]).strip() or DEFAULTS["app_name"]
    if cfg["default_locale"] not in LOCALES:
        raise ConfigError(_("default_locale must be one of: %(values)s", values=", ".join(LOCALES)))
    return cfg


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict:
    file_cfg, cfg_path = read_config_file(path)
    return normalize(file_cfg, cfg_path, overrides)


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
    return out


def runtime_view(cfg: dict) -> dict:
    """Extrae las secciones editables desde la web."""
    return {k: copy.deepcopy(cfg[k]) for k in RUNTIME_SECTIONS}

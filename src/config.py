"""Carga y validación de la configuración (config.json)."""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import sys
from pathlib import Path

DEFAULTS: dict = {
    "app_name": "StorageWeb",
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
        "threads": 8,
        # True si hay un proxy inverso (nginx) delante que envía X-Forwarded-*
        "behind_proxy": True,
        "max_upload_mb": 2048,
    },
    # Si se deja vacío se genera y guarda en <data_dir>/secret_key
    "secret_key": "",
    "data_dir": "data",
    "session": {
        "lifetime_hours": 8,
        # Debe ser True en producción (HTTPS). Ponlo a False solo para pruebas en http://localhost
        "cookie_secure": True,
    },
    "storage": {
        # {username} se sustituye por el nombre de usuario (saneado)
        "home_template": "data/homes/{username}",
        "create_home": True,
        "show_hidden": False,
        # Lista de rutas compartidas:
        # {"name": "compartido", "label": "Compartido", "path": "/srv/storageweb/shared",
        #  "read_only": false, "users": ["*"], "groups": []}
        "shares": [],
    },
    "auth": {
        "local": {"enabled": True},
        "pam": {
            # Usuarios del sistema operativo (solo Linux/macOS, requiere python-pam)
            "enabled": False,
            "service": "login",
            # Si no está vacío, solo pueden entrar miembros de estos grupos del SO
            "allowed_groups": [],
            # True = usar el home real del usuario (/home/usuario) en vez de home_template
            "use_system_home": False,
        },
        "entra": {
            "enabled": False,
            "tenant_id": "",
            "client_id": "",
            "client_secret": "",
            # Recomendado fijarla explícitamente: https://files.midominio.com/auth/entra/callback
            "redirect_uri": "",
            "scopes": ["User.Read"],
            "button_label": "Iniciar sesión con Microsoft",
            # Claim usado como nombre de usuario
            "username_claim": "preferred_username",
            # True = "juan@contoso.com" -> "juan" (cuidado con colisiones con usuarios locales)
            "strip_domain": False,
            # IDs de grupo o nombres de App Role permitidos (vacío = cualquiera del tenant)
            "allowed_groups": [],
            # Cerrar también la sesión de Microsoft al salir
            "single_logout": False,
        },
    },
    "security": {
        "max_login_failures": 5,
        "lockout_minutes": 15,
    },
}

SHARE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ConfigError(Exception):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def default_config_path() -> Path:
    env = os.environ.get("STORAGEWEB_CONFIG")
    if env:
        return Path(env)
    if sys.platform != "win32":
        system = Path("/etc/storageweb/config.json")
        if system.exists():
            return system
    return Path(__file__).resolve().parent.parent / "config.json"


def _resolve(base_dir: Path, value: str) -> Path:
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else (base_dir / p)


def load_config(path: str | os.PathLike | None = None) -> dict:
    cfg_path = Path(path) if path else default_config_path()
    user_cfg: dict = {}
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                user_cfg = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"JSON inválido en {cfg_path}: {exc}") from exc
    cfg = _deep_merge(DEFAULTS, user_cfg)
    base_dir = cfg_path.resolve().parent
    cfg["_config_path"] = str(cfg_path)

    # Rutas relativas se resuelven respecto al directorio del config.json
    data_dir = _resolve(base_dir, cfg["data_dir"])
    cfg["data_dir"] = str(data_dir)
    cfg["database"] = str(_resolve(base_dir, cfg.get("database") or str(data_dir / "storageweb.db")))

    tmpl = cfg["storage"]["home_template"]
    if "{username}" not in tmpl:
        raise ConfigError("storage.home_template debe contener {username}")
    # Se resuelve solo la parte fija; {username} se sustituye en tiempo de ejecución
    if not Path(os.path.expanduser(tmpl.split("{username}")[0] or ".")).is_absolute():
        tmpl = str(base_dir / tmpl)
    cfg["storage"]["home_template"] = os.path.expanduser(tmpl)

    seen = {"home"}
    shares = []
    for share in cfg["storage"]["shares"]:
        name = share.get("name", "")
        if not SHARE_NAME_RE.match(name):
            raise ConfigError(f"Nombre de share inválido '{name}' (solo letras, números, _ y -)")
        if name.lower() in seen:
            raise ConfigError(f"Nombre de share duplicado o reservado: '{name}'")
        seen.add(name.lower())
        if not share.get("path"):
            raise ConfigError(f"El share '{name}' no tiene 'path'")
        shares.append({
            "name": name,
            "label": share.get("label") or name,
            "path": str(_resolve(base_dir, share["path"])),
            "read_only": bool(share.get("read_only", False)),
            "users": [u.lower() for u in share.get("users", ["*"])],
            "groups": [g.lower() for g in share.get("groups", [])],
        })
    cfg["storage"]["shares"] = shares

    entra = cfg["auth"]["entra"]
    if entra["enabled"]:
        missing = [k for k in ("tenant_id", "client_id", "client_secret") if not entra.get(k)]
        if missing:
            raise ConfigError(f"auth.entra activado pero faltan: {', '.join(missing)}")
    if cfg["auth"]["pam"]["enabled"] and sys.platform == "win32":
        raise ConfigError("auth.pam no está disponible en Windows")

    return cfg


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

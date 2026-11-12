#!/bin/sh
# Entrypoint de la imagen Docker de StorageWeb.
#
# 1. Si no existe $STORAGEWEB_CONFIG (por defecto /data/config.json), genera uno para contenedor.
# 2. Si se indica STORAGEWEB_ADMIN_USER y ese usuario no existe, lo crea con rol admin.
#    La contraseña sale de STORAGEWEB_ADMIN_PASSWORD o de STORAGEWEB_ADMIN_PASSWORD_FILE (secrets).
# 3. Ejecuta "storageweb <argumentos>" (por defecto "serve").
#
# Variables para la configuración generada (solo se usan la primera vez):
#   STORAGEWEB_PORT (8080)  STORAGEWEB_BEHIND_PROXY (true)  STORAGEWEB_COOKIE_SECURE (true)
#   STORAGEWEB_MAX_UPLOAD_MB (2048)  STORAGEWEB_APP_NAME (StorageWeb)
set -e

CONFIG="${STORAGEWEB_CONFIG:-/data/config.json}"
export STORAGEWEB_CONFIG="$CONFIG"

if [ ! -f "$CONFIG" ]; then
  echo "storageweb: creando configuración inicial en $CONFIG"
  mkdir -p "$(dirname "$CONFIG")"
  python - "$CONFIG" <<'EOF'
import json
import os
import sys


def flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


cfg = {
    "app_name": os.environ.get("STORAGEWEB_APP_NAME", "StorageWeb"),
    "server": {
        "host": "0.0.0.0",
        "port": int(os.environ.get("STORAGEWEB_PORT", "8080")),
        "behind_proxy": flag("STORAGEWEB_BEHIND_PROXY", "true"),
        "max_upload_mb": int(os.environ.get("STORAGEWEB_MAX_UPLOAD_MB", "2048")),
    },
    "data_dir": "/data/db",
    "session": {"cookie_secure": flag("STORAGEWEB_COOKIE_SECURE", "true")},
    "storage": {
        "home_template": "/data/files/homes/{username}",
        "create_home": True,
        "create_shares": True,
        "shares": [{"name": "compartido", "label": "Compartido", "path": "/data/files/shared",
                    "read_only": False, "users": ["*"], "groups": []}],
    },
    "auth": {"local": {"enabled": True}, "pam": {"enabled": False}},
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
EOF
fi

if [ "${1:-serve}" = "serve" ] && [ -n "$STORAGEWEB_ADMIN_USER" ]; then
  if ! storageweb user-exists "$STORAGEWEB_ADMIN_USER"; then
    if [ -n "$STORAGEWEB_ADMIN_PASSWORD_FILE" ] && [ -f "$STORAGEWEB_ADMIN_PASSWORD_FILE" ]; then
      STORAGEWEB_ADMIN_PASSWORD="$(cat "$STORAGEWEB_ADMIN_PASSWORD_FILE")"
    fi
    if [ -z "$STORAGEWEB_ADMIN_PASSWORD" ]; then
      echo "storageweb: STORAGEWEB_ADMIN_USER sin contraseña (usa STORAGEWEB_ADMIN_PASSWORD o _FILE)" >&2
      exit 1
    fi
    printf '%s\n' "$STORAGEWEB_ADMIN_PASSWORD" | \
      storageweb user-add "$STORAGEWEB_ADMIN_USER" --role admin --password-stdin
  fi
fi
unset STORAGEWEB_ADMIN_PASSWORD

exec storageweb "$@"

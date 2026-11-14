#!/bin/sh
# Entrypoint de la imagen Docker de StorageWeb.
#
# 1. Si no existe $STORAGEWEB_CONFIG (por defecto /data/config.json), genera uno para contenedor.
# 2. Si se indica STORAGEWEB_ADMIN_USER y ese usuario no existe, lo crea con rol admin.
#    La contraseña sale de STORAGEWEB_ADMIN_PASSWORD o de STORAGEWEB_ADMIN_PASSWORD_FILE (secrets).
# 3. Ejecuta "storageweb <argumentos>" (por defecto "serve").
#
# La configuración generada solo lleva lo propio del contenedor (escucha en 0.0.0.0 y rutas del
# volumen /data). El resto se cambia desde la web o con variables de entorno, que se leen en cada
# arranque y bloquean el campo en la web: STORAGEWEB_<RUTA> con __ entre niveles
# (STORAGEWEB_AUTH__ENTRA__CLIENT_ID) y los nombres cortos STORAGEWEB_PORT, STORAGEWEB_BEHIND_PROXY,
# STORAGEWEB_COOKIE_SECURE, STORAGEWEB_MAX_UPLOAD_MB, STORAGEWEB_PROXY_HOPS y STORAGEWEB_PUBLIC_URL.
set -e

CONFIG="${STORAGEWEB_CONFIG:-/data/config.json}"
export STORAGEWEB_CONFIG="$CONFIG"

if [ ! -f "$CONFIG" ]; then
  echo "storageweb: creando configuración inicial en $CONFIG"
  mkdir -p "$(dirname "$CONFIG")"
  python - "$CONFIG" <<'EOF'
import json
import sys

cfg = {
    "server": {"host": "0.0.0.0"},
    "data_dir": "/data/db",
    "storage": {"home_template": "/data/files/homes/{username}"},
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

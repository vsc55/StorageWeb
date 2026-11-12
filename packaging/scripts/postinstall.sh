#!/bin/sh
# Configuración posterior a la instalación de StorageWeb. Idempotente.
# La usan packaging/install.sh (instalación desde el código) y los paquetes .deb/.rpm (postinst).
#
# Requiere que $APP_DIR/wheels contenga el wheel de storageweb (y, para instalar sin conexión,
# los de sus dependencias).
#
# Variables (con valores por defecto):
#   APP_USER APP_GROUP APP_DIR CONF_DIR DATA_DIR STORAGE_DIR
set -e

APP_USER="${APP_USER:-storageweb}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
APP_DIR="${APP_DIR:-/opt/storageweb}"
CONF_DIR="${CONF_DIR:-/etc/storageweb}"
DATA_DIR="${DATA_DIR:-/var/lib/storageweb}"
STORAGE_DIR="${STORAGE_DIR:-/srv/storageweb}"
SHARE_DIR="${SHARE_DIR:-/usr/share/storageweb}"
VENV="$APP_DIR/venv"
WHEELS="$APP_DIR/wheels"

log() { echo "storageweb: $*"; }

# --- usuario y grupo del servicio ------------------------------------------------
if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
  groupadd --system "$APP_GROUP"
fi
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  NOLOGIN=/usr/sbin/nologin
  [ -x "$NOLOGIN" ] || NOLOGIN=/sbin/nologin
  useradd --system --gid "$APP_GROUP" --home-dir "$DATA_DIR" --no-create-home \
          --shell "$NOLOGIN" "$APP_USER"
  log "creado el usuario de servicio '$APP_USER'"
fi

# --- directorios -----------------------------------------------------------------
install -d -m 0750 -o root        -g "$APP_GROUP" "$CONF_DIR"
install -d -m 0750 -o "$APP_USER" -g "$APP_GROUP" "$DATA_DIR"
for d in "$STORAGE_DIR" "$STORAGE_DIR/homes" "$STORAGE_DIR/shared" "$STORAGE_DIR/public"; do
  [ -d "$d" ] || install -d -m 2770 -o "$APP_USER" -g "$APP_GROUP" "$d"
done

# --- configuración (contiene el client_secret: solo lectura para el servicio) -----
if [ ! -f "$CONF_DIR/config.json" ] && [ -f "$SHARE_DIR/config.example.json" ]; then
  cp "$SHARE_DIR/config.example.json" "$CONF_DIR/config.json"
fi
if [ -f "$CONF_DIR/config.json" ]; then
  chown root:"$APP_GROUP" "$CONF_DIR/config.json"
  chmod 0640 "$CONF_DIR/config.json"
fi

# --- entorno virtual Python --------------------------------------------------------
SYS_PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ -x "$VENV/bin/python" ]; then
  VENV_PY_VER="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)"
  if [ "$VENV_PY_VER" != "$SYS_PY_VER" ]; then
    log "Python cambió ($VENV_PY_VER -> $SYS_PY_VER), se recrea el venv"
    rm -rf "$VENV"
  fi
fi
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"

PIP="$VENV/bin/python -m pip --disable-pip-version-check -q"
if $PIP install --upgrade --force-reinstall --no-index --find-links "$WHEELS" storageweb 2>/dev/null; then
  log "instalado desde los wheels incluidos (sin conexión)"
else
  log "faltan wheels para este Python; se descargan las dependencias de PyPI"
  $PIP install --upgrade --find-links "$WHEELS" storageweb
fi

# --- base de datos (crea o migra el esquema) ---------------------------------------
( cd "$DATA_DIR" && runuser -u "$APP_USER" -- env STORAGEWEB_CONFIG="$CONF_DIR/config.json" \
    "$VENV/bin/storageweb" init-db ) || log "AVISO: no se pudo inicializar la BD (revisa config.json)"

# --- servicio ---------------------------------------------------------------------
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload
  systemctl enable storageweb.service >/dev/null 2>&1 || true
  if ! systemctl restart storageweb.service; then
    log "AVISO: el servicio no arrancó. Revisa: journalctl -u storageweb -n 50"
  fi
fi

log "listo. Config: $CONF_DIR/config.json | Primer admin: sudo storageweb-admin user-add admin --role admin"
exit 0

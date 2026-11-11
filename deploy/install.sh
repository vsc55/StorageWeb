#!/usr/bin/env bash
# Instalador de StorageWeb para Ubuntu (22.04 / 24.04).
#
# Uso:  sudo ./deploy/install.sh [--pam] [--nginx]
#
# Variables opcionales (para cambiar el usuario/rutas del servicio):
#   APP_USER=storageweb APP_DIR=/opt/storageweb CONF_DIR=/etc/storageweb \
#   DATA_DIR=/var/lib/storageweb STORAGE_DIR=/srv/storageweb sudo -E ./deploy/install.sh
set -euo pipefail

APP_USER="${APP_USER:-storageweb}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
APP_DIR="${APP_DIR:-/opt/storageweb}"
CONF_DIR="${CONF_DIR:-/etc/storageweb}"
DATA_DIR="${DATA_DIR:-/var/lib/storageweb}"
STORAGE_DIR="${STORAGE_DIR:-/srv/storageweb}"
WITH_PAM=0
WITH_NGINX=0

for arg in "$@"; do
  case "$arg" in
    --pam)   WITH_PAM=1 ;;
    --nginx) WITH_NGINX=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Ejecuta como root (sudo)." >&2; exit 1; }

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log() { echo -e "\e[1;34m==>\e[0m $*"; }

log "Instalando dependencias del sistema"
apt-get update -qq
PKGS=(python3 python3-venv python3-pip rsync)
[[ $WITH_NGINX -eq 1 ]] && PKGS+=(nginx certbot python3-certbot-nginx)
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${PKGS[@]}"

log "Creando usuario de servicio '$APP_USER'"
if ! getent group "$APP_GROUP" >/dev/null; then
  groupadd --system "$APP_GROUP"
fi
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --gid "$APP_GROUP" --home-dir "$DATA_DIR" --no-create-home \
          --shell /usr/sbin/nologin "$APP_USER"
fi
if [[ $WITH_PAM -eq 1 ]]; then
  # pam_unix necesita leer /etc/shadow (el servicio usa NoNewPrivileges, no puede usar unix_chkpwd)
  usermod -aG shadow "$APP_USER"
  getent group storageweb-users >/dev/null || groupadd storageweb-users
  log "PAM: añade los usuarios permitidos al grupo 'storageweb-users' (usermod -aG storageweb-users <user>)"
fi

log "Copiando aplicación a $APP_DIR"
install -d -m 0755 -o root -g root "$APP_DIR"
rsync -a --delete --exclude 'venv' --exclude 'data' --exclude 'config.json' \
      --exclude '__pycache__' --exclude '.git' --exclude 'deploy' \
      "$SRC_DIR"/ "$APP_DIR"/
chown -R root:root "$APP_DIR"

log "Creando entorno virtual Python"
[[ -d "$APP_DIR/venv" ]] || python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

log "Creando directorios de datos"
install -d -m 0750 -o root      -g "$APP_GROUP" "$CONF_DIR"
install -d -m 0750 -o "$APP_USER" -g "$APP_GROUP" "$DATA_DIR"
install -d -m 2770 -o "$APP_USER" -g "$APP_GROUP" "$STORAGE_DIR"
install -d -m 2770 -o "$APP_USER" -g "$APP_GROUP" "$STORAGE_DIR/homes"
install -d -m 2770 -o "$APP_USER" -g "$APP_GROUP" "$STORAGE_DIR/shared"
install -d -m 2770 -o "$APP_USER" -g "$APP_GROUP" "$STORAGE_DIR/public"

if [[ ! -f "$CONF_DIR/config.json" ]]; then
  log "Creando $CONF_DIR/config.json"
  sed -e "s#/var/lib/storageweb#$DATA_DIR#g" -e "s#/srv/storageweb#$STORAGE_DIR#g" \
      "$SRC_DIR/config.example.json" > "$CONF_DIR/config.json"
  [[ $WITH_PAM -eq 1 ]] && python3 - "$CONF_DIR/config.json" <<'EOF'
import json, sys
p = sys.argv[1]; c = json.load(open(p))
c["auth"]["pam"]["enabled"] = True
json.dump(c, open(p, "w"), indent=2, ensure_ascii=False)
EOF
else
  log "Se conserva el config.json existente"
fi
# root escribe, el servicio solo lee (contiene el client_secret de Entra)
chown root:"$APP_GROUP" "$CONF_DIR/config.json"
chmod 0640 "$CONF_DIR/config.json"

log "Inicializando base de datos"
sudo -u "$APP_USER" STORAGEWEB_CONFIG="$CONF_DIR/config.json" \
     "$APP_DIR/venv/bin/python" "$APP_DIR/manage.py" init-db

log "Instalando comando 'storageweb-admin'"
cat > /usr/local/bin/storageweb-admin <<EOF
#!/bin/sh
# Ejecuta manage.py como el usuario del servicio
cd "$APP_DIR" && exec sudo -u "$APP_USER" STORAGEWEB_CONFIG="$CONF_DIR/config.json" \\
  "$APP_DIR/venv/bin/python" "$APP_DIR/manage.py" "\$@"
EOF
chmod 0755 /usr/local/bin/storageweb-admin

log "Instalando servicio systemd"
sed -e "s#@APP_USER@#$APP_USER#g" -e "s#@APP_GROUP@#$APP_GROUP#g" -e "s#@APP_DIR@#$APP_DIR#g" \
    -e "s#@CONF_DIR@#$CONF_DIR#g" -e "s#@DATA_DIR@#$DATA_DIR#g" -e "s#@STORAGE_DIR@#$STORAGE_DIR#g" \
    "$SRC_DIR/deploy/storageweb.service" > /etc/systemd/system/storageweb.service
systemctl daemon-reload
systemctl enable storageweb >/dev/null
systemctl restart storageweb

if [[ $WITH_NGINX -eq 1 && ! -f /etc/nginx/sites-available/storageweb ]]; then
  log "Copiando plantilla de nginx (edita server_name y certificados)"
  cp "$SRC_DIR/deploy/nginx-storageweb.conf" /etc/nginx/sites-available/storageweb
  echo "   Edita /etc/nginx/sites-available/storageweb y luego:"
  echo "   ln -s /etc/nginx/sites-available/storageweb /etc/nginx/sites-enabled/ && certbot --nginx -d <dominio>"
fi

sleep 1
systemctl --no-pager --lines=5 status storageweb || true
cat <<EOF

StorageWeb instalado.
  Config:     $CONF_DIR/config.json   (después de editar: systemctl restart storageweb)
  Datos/BD:   $DATA_DIR
  Archivos:   $STORAGE_DIR
  Servicio:   systemctl status storageweb  |  journalctl -u storageweb -f
  Usuarios:   sudo storageweb-admin user-add <usuario>
              sudo storageweb-admin user-list
EOF

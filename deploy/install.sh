#!/usr/bin/env bash
# Instalación manual de StorageWeb en Ubuntu (22.04 / 24.04 / 26.04) desde el código fuente.
# (Alternativa: instalar el .deb de la release de GitHub: sudo apt install ./storageweb_X.Y.Z_amd64.deb)
#
# Uso:  sudo ./deploy/install.sh [--pam] [--nginx]
#
# Variables opcionales (para cambiar el usuario/rutas del servicio):
#   APP_USER=storageweb APP_DIR=/opt/storageweb CONF_DIR=/etc/storageweb \
#   DATA_DIR=/var/lib/storageweb STORAGE_DIR=/srv/storageweb sudo -E ./deploy/install.sh
set -euo pipefail

export APP_USER="${APP_USER:-storageweb}"
export APP_GROUP="${APP_GROUP:-$APP_USER}"
export APP_DIR="${APP_DIR:-/opt/storageweb}"
export CONF_DIR="${CONF_DIR:-/etc/storageweb}"
export DATA_DIR="${DATA_DIR:-/var/lib/storageweb}"
export STORAGE_DIR="${STORAGE_DIR:-/srv/storageweb}"
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
render() {  # render <plantilla> <destino>
  sed -e "s#@APP_USER@#$APP_USER#g" -e "s#@APP_GROUP@#$APP_GROUP#g" -e "s#@APP_DIR@#$APP_DIR#g" \
      -e "s#@CONF_DIR@#$CONF_DIR#g" -e "s#@DATA_DIR@#$DATA_DIR#g" -e "s#@STORAGE_DIR@#$STORAGE_DIR#g" \
      "$1" > "$2"
}

log "Instalando dependencias del sistema"
apt-get update -qq
PKGS=(python3 python3-venv python3-pip rsync)
if [[ $WITH_NGINX -eq 1 ]]; then PKGS+=(nginx certbot python3-certbot-nginx); fi
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${PKGS[@]}"

log "Copiando aplicación a $APP_DIR"
install -d -m 0755 -o root -g root "$APP_DIR"
rsync -a --delete \
      --exclude 'venv' --exclude '.venv' --exclude 'wheels' --exclude 'config.json' --exclude '__pycache__' \
      --exclude '.git' --exclude '.github' --exclude '.vscode' --exclude '.dev' --exclude 'tests' \
      --exclude 'build' --exclude 'dist' --exclude 'packaging' --exclude 'data' \
      "$SRC_DIR"/ "$APP_DIR"/
chown -R root:root "$APP_DIR"

mkdir -p "$CONF_DIR"
if [[ ! -f "$CONF_DIR/config.json" ]]; then
  log "Creando $CONF_DIR/config.json"
  sed -e "s#/var/lib/storageweb#$DATA_DIR#g" -e "s#/srv/storageweb#$STORAGE_DIR#g" \
      "$SRC_DIR/config/config.example.json" > "$CONF_DIR/config.json"
  if [[ $WITH_PAM -eq 1 ]]; then
    python3 - "$CONF_DIR/config.json" <<'EOF'
import json, sys
p = sys.argv[1]
c = json.load(open(p, encoding="utf-8"))
c["auth"]["pam"]["enabled"] = True
json.dump(c, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
EOF
  fi
else
  log "Se conserva el config.json existente"
fi

log "Instalando servicio systemd y comando storageweb-admin"
render "$SRC_DIR/deploy/storageweb.service" /etc/systemd/system/storageweb.service
render "$SRC_DIR/deploy/storageweb-admin" /usr/local/bin/storageweb-admin
chmod 0755 /usr/local/bin/storageweb-admin

if [[ $WITH_PAM -eq 1 ]]; then
  getent group "$APP_GROUP" >/dev/null || groupadd --system "$APP_GROUP"
  id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --gid "$APP_GROUP" --home-dir "$DATA_DIR" \
                                               --no-create-home --shell /usr/sbin/nologin "$APP_USER"
  # pam_unix necesita leer /etc/shadow (el servicio usa NoNewPrivileges y no puede usar unix_chkpwd)
  usermod -aG shadow "$APP_USER"
  getent group storageweb-users >/dev/null || groupadd storageweb-users
  log "PAM: añade los usuarios permitidos al grupo 'storageweb-users' (usermod -aG storageweb-users <user>)"
fi

log "Configurando usuario, directorios, entorno Python y servicio"
sh "$SRC_DIR/deploy/postinstall.sh"

if [[ $WITH_NGINX -eq 1 && ! -f /etc/nginx/sites-available/storageweb ]]; then
  log "Copiando plantilla de nginx (edita server_name y certificados)"
  cp "$SRC_DIR/deploy/nginx-storageweb.conf" /etc/nginx/sites-available/storageweb
  echo "   Edita /etc/nginx/sites-available/storageweb y luego:"
  echo "   ln -s /etc/nginx/sites-available/storageweb /etc/nginx/sites-enabled/ && certbot --nginx -d <dominio>"
fi

systemctl --no-pager --lines=5 status storageweb || true
cat <<EOF

StorageWeb instalado.
  Config:     $CONF_DIR/config.json   (después de editar: systemctl restart storageweb)
  Datos/BD:   $DATA_DIR
  Archivos:   $STORAGE_DIR
  Servicio:   systemctl status storageweb  |  journalctl -u storageweb -f
  Admin:      sudo storageweb-admin user-add admin --role admin   (luego entra en /admin)
EOF

#!/bin/sh
# deb: $1 = remove | purge | upgrade | failed-upgrade | abort-install | abort-upgrade | disappear
# rpm: $1 = 0 (desinstalar) | 1 (actualizar)
set -e
case "$1" in
  remove|purge|0)
    # El venv se crea en postinstall y no pertenece al paquete
    rm -rf /opt/storageweb/venv
    rmdir /opt/storageweb/wheels /opt/storageweb 2>/dev/null || true
    if [ -d /run/systemd/system ]; then systemctl daemon-reload || true; fi
    echo "storageweb: se conservan los datos en /var/lib/storageweb y /srv/storageweb y el usuario 'storageweb'."
    ;;
esac
exit 0

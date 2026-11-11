#!/bin/sh
# deb: $1 = remove | purge | upgrade | failed-upgrade | abort-install | abort-upgrade | disappear
# rpm: $1 = 0 (desinstalar) | 1 (actualizar)
set -e
case "$1" in
  remove|purge|0)
    # Ficheros generados en postinstall (no pertenecen al paquete)
    rm -rf /opt/storageweb/venv
    find /opt/storageweb -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
    rmdir /opt/storageweb 2>/dev/null || true
    [ -d /run/systemd/system ] && systemctl daemon-reload || true
    echo "storageweb: se conservan los datos en /var/lib/storageweb y /srv/storageweb y el usuario 'storageweb'."
    ;;
esac
exit 0

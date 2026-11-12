#!/bin/sh
# deb: $1 = remove | upgrade | deconfigure | failed-upgrade
# rpm: $1 = 0 (desinstalar) | 1 (actualizar)
set -e
case "$1" in
  remove|deconfigure|0)
    if [ -d /run/systemd/system ]; then
      systemctl disable --now storageweb.service >/dev/null 2>&1 || true
    fi
    ;;
esac
exit 0

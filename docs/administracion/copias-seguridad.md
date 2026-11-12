# Copias de seguridad

Hay que proteger dos cosas, y cada una se copia de forma distinta:

| Qué | Contiene | Cómo |
|---|---|---|
| **Estado del servicio** | Base de datos (usuarios, ajustes web, auditoría), `config.json`, `secret_key` | `storageweb backup` |
| **Archivos de los usuarios** | `/srv/storageweb` (homes y carpetas compartidas) | Herramientas incrementales: rsync, borg, restic o snapshots |

## `storageweb backup`

```bash
sudo storageweb-admin backup --keep 14
# /var/lib/storageweb/backups/storageweb-backup-20261112-031500.tar.gz
sudo storageweb-admin backup-list
```

- **Copia consistente** con el servicio en marcha: usa la API de backup en línea de SQLite y comprueba la integridad de la copia. Copiar el fichero `.db` a mano mientras el servicio escribe puede dar una copia dañada.
- **Contenido:** `manifest.json` (versión y esquema), `storageweb.db`, `config.json` y `secret_key`.
- **Permisos `0600`:** contiene hashes de contraseñas y el `client_secret`, así que guárdala cifrada fuera del servidor.
- **Rotación:** `--keep N` conserva las N más recientes de la carpeta. Con `--output DIR` eliges otra carpeta.

## Programar las copias

=== "systemd (deb, rpm, Gentoo)"

    El timer viene instalado pero desactivado: hace una copia diaria a las 03:15 y conserva 14.

    ```bash
    sudo systemctl enable --now storageweb-backup.timer
    systemctl list-timers storageweb-backup.timer
    journalctl -u storageweb-backup.service
    ```

    Para cambiar la hora o la retención, usa `sudo systemctl edit storageweb-backup.timer` o `storageweb-backup.service`.

=== "cron (OpenRC)"

    ```cron
    # /etc/cron.d/storageweb
    15 3 * * *  root  storageweb-admin backup --keep 14 >/dev/null
    ```

=== "Docker"

    ```bash
    docker exec storageweb storageweb backup --keep 14     # queda en el volumen: /data/db/backups
    ```

Después, sácalas del servidor con rsync, restic o similar. Una copia que solo está en el mismo disco no protege frente a la pérdida del disco.

## Archivos de los usuarios

Un ejemplo con restic:

```bash
restic -r sftp:backup@nas:/storageweb backup /srv/storageweb /var/lib/storageweb/backups
```

Se pueden copiar en caliente. Los ficheros `.sw-upload-*.part` son subidas en curso y se pueden excluir.

## Restaurar

1. Para el servicio: `sudo systemctl stop storageweb` (o `rc-service storageweb stop`, o `docker stop`).
2. Restaura:
   ```bash
   sudo storageweb-admin restore /ruta/storageweb-backup-AAAAMMDD-HHMMSS.tar.gz --force
   ```
   - Antes guarda la base de datos actual como `storageweb.db.antes-de-restaurar-<fecha>`.
   - Comprueba la integridad de la copia.
   - Restaura la `secret_key` y aplica las migraciones pendientes si la copia es de una versión anterior.
   - Se niega a restaurar copias de una versión **más nueva** que la instalada.
3. Si necesitas también la configuración, añade `--config-to /tmp/config.restaurado.json` y revísala antes de copiarla a `/etc/storageweb/config.json`.
4. Arranca el servicio y comprueba: `storageweb-admin check-config` y `storageweb-admin audit --limit 5`.

Restaura los archivos de los usuarios con la herramienta con la que los copiaste.

!!! tip "Prueba la restauración"
    Una copia que nunca se ha restaurado no es una copia. Restáurala de vez en cuando en otra máquina o en otro `data_dir`:
    `storageweb --config /tmp/prueba.json restore copia.tar.gz`.

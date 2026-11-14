# Rutas y variables de entorno

## Rutas por tipo de instalación

| | deb / rpm / `install.sh` | Gentoo | Docker | Desarrollo |
|---|---|---|---|---|
| Ejecutable | `/opt/storageweb/venv/bin/storageweb` | `/usr/bin/storageweb` | `storageweb` (en el `PATH`) | `.venv/…/storageweb` |
| CLI como servicio | `/usr/bin/storageweb-admin`¹ | `/usr/bin/storageweb-admin` | `docker exec … storageweb` | — |
| Configuración | `/etc/storageweb/config.json` | `/etc/storageweb/config.json` | `/data/config.json` | `config/config.dev.json` |
| Base de datos | `/var/lib/storageweb/storageweb.db` | igual | `/data/db/storageweb.db` | `.dev/data/` |
| `secret_key` | `/var/lib/storageweb/secret_key` | igual | `/data/db/secret_key` | `.dev/data/` |
| Copias | `/var/lib/storageweb/backups/` | igual | `/data/db/backups/` | `.dev/data/backups/` |
| Subidas a S3/SMB en curso | `/var/lib/storageweb/uploads/` | igual | `/data/db/uploads/` | `.dev/data/uploads/` |
| Archivos | `/srv/storageweb/{homes,shared,public}` | igual | `/data/files/` | `.dev/` |
| Servicio | `storageweb.service`, `storageweb-backup.{service,timer}` | igual + OpenRC `storageweb` | — | — |
| Log | journald | journald u `/var/log/storageweb/` | `docker logs` | consola |
| Ejemplos | `/usr/share/storageweb/` | igual | — | `config/` |

¹ Con `install.sh` se instala en `/usr/local/bin/storageweb-admin`.

## Ficheros temporales

- `.sw-upload-<id>.part`: subidas por partes en curso, en la carpeta de destino. Se ocultan en el listado y se borran a las 24 h de inactividad.
- `storageweb.db-wal` y `storageweb.db-shm`: ficheros de SQLite en modo WAL. No los borres con el servicio en marcha.
- `storageweb.db.antes-de-restaurar-<fecha>`: copia que deja `restore` antes de reemplazar la base de datos.

## Variables de entorno

| Variable | Uso |
|---|---|
| `STORAGEWEB_CONFIG` | Ruta de `config.json` (la definen la unidad systemd y el wrapper `storageweb-admin`) |
| `STORAGEWEB_LANG` | Idioma de la CLI (`es` o `en`). Si no está, se usan `LC_ALL`, `LC_MESSAGES` o `LANG`, y si tampoco, `en` |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | Proxy de salida para contactar con Entra ID (`oauth2` y `msal`) |
| `STORAGEWEB_ADMIN_USER`, `STORAGEWEB_ADMIN_PASSWORD`, `STORAGEWEB_ADMIN_PASSWORD_FILE` | Solo Docker: admin inicial |
| `STORAGEWEB_PORT`, `STORAGEWEB_BEHIND_PROXY`, `STORAGEWEB_COOKIE_SECURE`, `STORAGEWEB_MAX_UPLOAD_MB`, `STORAGEWEB_APP_NAME` | Solo Docker: valores al generar `config.json` |
| `APP_USER`, `APP_GROUP`, `APP_DIR`, `CONF_DIR`, `DATA_DIR`, `STORAGE_DIR`, `SHARE_DIR` | Solo `packaging/install.sh`: usuario y rutas de la instalación |

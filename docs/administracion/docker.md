# Docker

Cada release publica la imagen `ghcr.io/<owner>/<repo>` para **amd64** y **arm64**, con las etiquetas:

- `X.Y.Z` y `X.Y`;
- `latest`, que solo se mueve con versiones estables, no con *pre-releases*.

## Arranque

```bash
docker run -d --name storageweb --restart unless-stopped \
  -p 8080:8080 -v storageweb-data:/data \
  -e STORAGEWEB_ADMIN_USER=admin -e STORAGEWEB_ADMIN_PASSWORD='una-clave-larga' \
  ghcr.io/<owner>/<repo>:latest
```

Con Compose, usando el `compose.yaml` del repositorio:

```bash
printf 'una-clave-larga' > admin_password.txt      # se pasa al contenedor como secret
docker compose up -d
```

## Qué hace el contenedor

1. En el primer arranque genera `/data/config.json` con valores para contenedor:
   - escucha en `0.0.0.0:8080`;
   - datos en `/data/db` y archivos en `/data/files`;
   - una carpeta compartida `compartido`.

   A partir de ahí es tu fichero y puedes editarlo.
2. Si defines `STORAGEWEB_ADMIN_USER` y ese usuario no existe, lo crea con rol `admin`. La contraseña se pasa por stdin, nunca como argumento visible.
3. Ejecuta `storageweb serve` como el usuario sin privilegios `storageweb` (uid/gid **10001**).

## Volumen `/data`

```
/data/
  config.json          configuración (editable)
  db/                  storageweb.db, secret_key, backups/
  files/homes/<usuario>
  files/shared/
```

Para guardar los archivos en una carpeta del host:

```bash
sudo chown -R 10001:10001 /srv/archivos
docker run ... -v storageweb-data:/data -v /srv/archivos:/data/files ...
```

## Variables de entorno

| Variable | Uso |
|---|---|
| `STORAGEWEB_ADMIN_USER` | Usuario admin que se crea si no existe |
| `STORAGEWEB_ADMIN_PASSWORD` / `STORAGEWEB_ADMIN_PASSWORD_FILE` | Su contraseña (mínimo 10 caracteres). Preferible `_FILE` con un *secret* |
| `STORAGEWEB_CONFIG` | Ruta del config (por defecto `/data/config.json`) |
| `STORAGEWEB_PORT` | Puerto (por defecto `8080`) |
| `STORAGEWEB_BEHIND_PROXY` | `true`/`false` (por defecto `true`) |
| `STORAGEWEB_COOKIE_SECURE` | `true`/`false` (por defecto `true`) |
| `STORAGEWEB_PUBLIC_URL` | Nombre público (FQDN), p. ej. `files.midominio.com`; se asume HTTPS (por defecto vacío: el host de cada petición) |
| `STORAGEWEB_PROXY_HOPS` | Proxies encadenados delante del contenedor (por defecto `1`) |
| `STORAGEWEB_MAX_UPLOAD_MB` | Máximo por petición (por defecto `2048`) |
| `STORAGEWEB_APP_NAME` | Nombre visible |
| `HTTPS_PROXY`, `NO_PROXY` | Proxy de salida para Entra ID |

Todas las variables salvo las de admin y proxy **solo se usan al generar** `config.json` la primera vez. Después, cambia el fichero o usa las páginas de la administración.

!!! tip "Probar sin HTTPS"
    `-e STORAGEWEB_COOKIE_SECURE=false -e STORAGEWEB_BEHIND_PROXY=false` en un volumen nuevo. Si no, el login vuelve a la página de inicio, porque el navegador no envía la cookie segura por HTTP.

## Operación

```bash
docker exec -it storageweb storageweb user-list
docker exec -it storageweb storageweb backup --keep 14      # copia en /data/db/backups
docker logs -f storageweb
docker inspect -f '{{.State.Health.Status}}' storageweb     # healthcheck contra /healthz
```

Actualizar: `docker pull ghcr.io/<owner>/<repo>:latest`, y luego `docker rm -f storageweb` y el mismo `docker run`. Las migraciones de la base de datos se aplican solas. Haz antes una [copia de seguridad](copias-seguridad.md).

## Compilar la imagen

```bash
docker build --build-arg VERSION=1.2.0 -t storageweb:1.2.0 .
```

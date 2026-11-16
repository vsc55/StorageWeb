# StorageWeb

Servidor web para **subir y descargar archivos** desde el navegador. Está escrito en Python (Flask + Waitress), funciona en Linux, Windows y macOS, y se despliega en Ubuntu/Debian, RHEL/Fedora, Gentoo o Docker.

- **Inicio de sesión:** usuarios locales, usuarios del sistema (PAM) y **Microsoft Entra ID** (SSO por OAuth2/OIDC propio o MSAL).
- **Roles:** `admin` y `user`, con permisos configurables y un panel web de usuarios, ajustes y auditoría.
- **Almacenamiento:** carpeta personal por usuario y carpetas compartidas por usuario o grupo (también de solo lectura), en el disco del servidor, en montajes (NFS, SMB, rclone) o directamente en S3, SMB, SFTP, WebDAV, FTP o Azure Blob Storage.
- **Archivos grandes:** subidas por partes reanudables y descargas con `Range`, sin límite de tamaño.
- **Operación:** auditoría completa, `storageweb backup`/`restore`, `/healthz` y servicio systemd endurecido.

## Instalación rápida

```bash
# Ubuntu / Debian (paquete de la release)
sudo apt install ./storageweb_X.Y.Z_amd64.deb
sudo storageweb-admin user-add admin --role admin

# Docker
docker run -d -p 8080:8080 -v storageweb-data:/data \
  -e STORAGEWEB_ADMIN_USER=admin -e STORAGEWEB_ADMIN_PASSWORD='una-clave-larga' \
  ghcr.io/<owner>/<repo>:latest
```

En producción, ponlo detrás de un proxy con HTTPS ([guía](docs/administracion/https.md)).

## Documentación

La documentación completa se publica en GitHub Pages con cada release. También se puede leer en [`docs/`](docs/index.md) o servir en local con `mkdocs serve`.

| | |
|---|---|
| **Usar** | [Guía de uso](docs/uso/index.md) |
| **Instalar y operar** | [Instalación](docs/administracion/instalacion.md) · [Docker](docs/administracion/docker.md) · [Gentoo](docs/administracion/gentoo.md) · [HTTPS](docs/administracion/https.md) · [Configuración](docs/administracion/configuracion.md) · [Entra ID](docs/administracion/entra-id.md) · [Usuarios y permisos](docs/administracion/usuarios-y-permisos.md) · [Copias de seguridad](docs/administracion/copias-seguridad.md) · [Actualización](docs/administracion/actualizacion.md) · [Seguridad](docs/administracion/seguridad.md) · [Problemas](docs/administracion/solucion-problemas.md) |
| **Referencia** | [Configuración](docs/referencia/configuracion.md) · [CLI](docs/referencia/cli.md) · [API](docs/referencia/api.md) · [Auditoría](docs/referencia/auditoria.md) · [Rutas](docs/referencia/rutas.md) |
| **Arquitectura** | [Visión general](docs/arquitectura/index.md) · [Flujos](docs/arquitectura/flujos.md) · [Datos](docs/arquitectura/datos.md) · [Modelo de seguridad](docs/arquitectura/seguridad.md) · [Decisiones (ADR)](docs/arquitectura/decisiones/index.md) |
| **Desarrollar** | [Entorno y convenciones](docs/desarrollo/index.md) · [Extender](docs/desarrollo/extender.md) · [Documentación](docs/desarrollo/documentacion.md) · [Releases](docs/desarrollo/releases.md) |

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,docs]"
storageweb --config config/config.dev.json user-add admin --role admin
storageweb --config config/config.dev.json serve --dev     # http://127.0.0.1:8080, con recarga automática
python -m pytest -q
```

En VS Code hay tareas para todo esto (*Tasks: Run Task → StorageWeb: …*) y **Ctrl+Shift+B** lanza el servidor de pruebas.

Más: [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) · [SECURITY.md](SECURITY.md)

## Licencia

StorageWeb es software libre: puedes usarlo, estudiarlo, modificarlo y redistribuirlo bajo los términos de la [GNU General Public License](LICENSE), versión 3 o (a tu elección) cualquier versión posterior. Si distribuyes StorageWeb, modificado o no, tienes que hacerlo con su código fuente y bajo esta misma licencia. Se ofrece **sin ninguna garantía**; consulta [LICENSE](LICENSE) para los detalles.

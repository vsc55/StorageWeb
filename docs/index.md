# StorageWeb

StorageWeb es un servidor web para **subir y descargar archivos** desde el navegador. Está escrito en Python, funciona en Linux, Windows y macOS, y se despliega en Ubuntu (`.deb`), RHEL/Fedora (`.rpm`), Gentoo (ebuild) o Docker.

- **Inicio de sesión:** usuarios locales, usuarios del sistema operativo (PAM) y **Microsoft Entra ID** (SSO).
- **Roles:** `admin` (gestiona usuarios y ajustes desde la web) y `user` (trabaja con archivos según los permisos que defina el admin).
- **Almacenamiento:** una carpeta personal por usuario y carpetas compartidas por usuario o grupo, que pueden ser de solo lectura.
- **Archivos grandes:** subidas por partes reanudables y descargas reanudables, sin límite de tamaño.
- **Operación:** auditoría de todas las acciones, copias de seguridad con un comando, `/healthz` para la monitorización y servicio endurecido con systemd.

## ¿Qué estás buscando?

| Soy… | Empieza por |
|---|---|
| **Usuario** y quiero subir o descargar archivos | [Uso](uso/index.md) |
| **Administrador** y voy a instalarlo | [Instalación](administracion/instalacion.md) → [HTTPS](administracion/https.md) → [Configuración](administracion/configuracion.md) |
| **Administrador** y quiero el inicio de sesión con Microsoft | [Microsoft Entra ID](administracion/entra-id.md) |
| **Administrador** de un servidor en producción | [Copias de seguridad](administracion/copias-seguridad.md), [Seguridad](administracion/seguridad.md), [Solución de problemas](administracion/solucion-problemas.md) |
| Busco una opción, un comando o un endpoint concreto | [Referencia](referencia/configuracion.md) |
| **Desarrollador** | [Arquitectura](arquitectura/index.md) y [Desarrollo](desarrollo/index.md) |

## Arranque rápido

=== "Ubuntu / Debian"

    ```bash
    sudo apt install ./storageweb_X.Y.Z_amd64.deb
    sudo storageweb-admin user-add admin --role admin
    ```

=== "Docker"

    ```bash
    docker run -d -p 8080:8080 -v storageweb-data:/data \
      -e STORAGEWEB_ADMIN_USER=admin -e STORAGEWEB_ADMIN_PASSWORD='una-clave-larga' \
      ghcr.io/<owner>/<repo>:latest
    ```

=== "Windows / macOS"

    ```bash
    pip install storageweb-X.Y.Z-py3-none-any.whl
    storageweb --config config.json user-add admin --role admin
    storageweb --config config.json serve
    ```

Después, entra con el usuario admin y abre el **Resumen** de la administración (o pulsa Ctrl+K para buscar un ajuste).

!!! warning "HTTPS"
    En producción pon delante un proxy con HTTPS ([guía de nginx](administracion/https.md)). Sin HTTPS, la cookie de sesión no se envía (`session.cookie_secure`) y Microsoft Entra ID rechaza la URL de vuelta.

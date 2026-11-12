# Instalación

## Requisitos

- **Sistema:**
  - Linux (Ubuntu 22.04+, Debian 12+, RHEL/Rocky/Alma 9+, Fedora o Gentoo) para producción;
  - Windows y macOS también funcionan, sin el servicio del sistema.
- **Python 3.9 o superior:** los paquetes usan el del sistema.
- **Proxy con HTTPS:** necesario en producción ([nginx](https.md)) y obligatorio para Entra ID.
- **Disco:** el que necesiten los archivos de los usuarios. La base de datos ocupa muy poco.

## Elegir el método

| Método | Cuándo |
|---|---|
| [Paquete `.deb` / `.rpm`](#paquetes-deb-y-rpm) | **Recomendado** en servidores Linux. Se instala sin conexión a Internet y crea el servicio systemd. |
| [Docker](docker.md) | Si ya usas contenedores o Kubernetes. |
| [Gentoo](gentoo.md) | Overlay con ebuild (OpenRC o systemd). |
| [Desde el código](#desde-el-codigo-fuente) | Rutas o usuario de servicio personalizados, o distribuciones sin paquete. |
| [Wheel (`pip`)](#windows-macos-y-otros) | Windows, macOS o pruebas. |

Todos los ficheros se descargan de la página de *releases* del repositorio. Comprueba su integridad con `sha256sum -c SHA256SUMS`.

## Paquetes deb y rpm

=== "Ubuntu / Debian"

    ```bash
    sudo apt install ./storageweb_X.Y.Z_amd64.deb      # o _arm64.deb
    ```

=== "RHEL / Rocky / Alma / Fedora"

    ```bash
    sudo dnf install ./storageweb-X.Y.Z.x86_64.rpm     # o .aarch64.rpm
    ```

El paquete hace lo siguiente:

1. Crea el usuario y el grupo de sistema `storageweb`.
2. Instala la aplicación en un entorno virtual en `/opt/storageweb/venv`, a partir de los *wheels* incluidos. Si falta algún wheel para tu versión de Python, lo descarga de PyPI.
3. Instala `/etc/storageweb/config.json` como fichero de configuración, que no se sobrescribe al actualizar.
4. Crea la base de datos y arranca `storageweb.service` en `127.0.0.1:8080`.

Crea el primer administrador y comprueba el estado:

```bash
sudo storageweb-admin user-add admin --role admin    # pide la contraseña
sudo storageweb-admin check-config
systemctl status storageweb
```

Siguientes pasos: [HTTPS con nginx](https.md), [configuración](configuracion.md) y [copias de seguridad](copias-seguridad.md).

## Desde el código fuente

En Ubuntu, desde una copia del repositorio o del `.tar.gz` de la release:

```bash
sudo ./packaging/install.sh --nginx        # --pam para permitir usuarios del sistema
sudo storageweb-admin user-add admin --role admin
```

Para cambiar el usuario del servicio o las rutas:

```bash
sudo APP_USER=svc-files STORAGE_DIR=/datos/files ./packaging/install.sh
```

Las variables disponibles son `APP_USER`, `APP_GROUP`, `APP_DIR`, `CONF_DIR`, `DATA_DIR`, `STORAGE_DIR` y `SHARE_DIR`. El script construye los wheels, crea el venv, instala las unidades systemd y ejecuta el mismo `postinstall` que los paquetes.

## Windows, macOS y otros

```bash
python -m venv venv
venv/bin/pip install storageweb-X.Y.Z-py3-none-any.whl     # Windows: venv\Scripts\pip
cp config.example.json config.json                         # y ajústalo
storageweb --config config.json user-add admin --role admin
storageweb --config config.json serve
```

En un `config.json` para pruebas en `http://localhost`, pon `"session": {"cookie_secure": false}` y `"server": {"behind_proxy": false}`.

## Qué se instala (paquetes)

| Qué | Dónde |
|---|---|
| Aplicación | `/opt/storageweb/venv` (instalada desde `/opt/storageweb/wheels`) |
| Configuración | `/etc/storageweb/config.json` (`root:storageweb`, `0640`) |
| Base de datos, `secret_key`, copias | `/var/lib/storageweb` |
| Archivos | `/srv/storageweb/{homes,shared,public}` |
| Servicios | `storageweb.service`, `storageweb-backup.timer` (desactivado) |
| CLI | `/usr/bin/storageweb-admin` |
| Ejemplos | `/usr/share/storageweb/` (`config.example.json`, plantilla de nginx) |

La lista completa está en [Rutas y variables de entorno](../referencia/rutas.md).

## Desinstalar

```bash
sudo apt remove storageweb      # o: sudo dnf remove storageweb
```

Se borran la aplicación y el venv. **Se conservan** los datos (`/var/lib/storageweb`, `/srv/storageweb`), la configuración y el usuario `storageweb`. Bórralos a mano si ya no los necesitas.

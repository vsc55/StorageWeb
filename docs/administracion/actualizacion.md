# Actualización

## Antes de actualizar

1. Lee el [registro de cambios](../proyecto/changelog.md), sobre todo los apartados **Cambios incompatibles** y **Notas de actualización**.
2. Haz una copia: `sudo storageweb-admin backup`.

## Cómo actualizar

=== "deb / rpm"

    ```bash
    sudo apt install ./storageweb_X.Y.Z_amd64.deb      # o: sudo dnf upgrade ./storageweb-X.Y.Z.x86_64.rpm
    ```

    El paquete reinstala la aplicación en el venv. Si ha cambiado la versión de Python del sistema, recrea el venv. Después aplica las migraciones y reinicia el servicio. `/etc/storageweb/config.json` no se sobrescribe: si el paquete trae uno nuevo, se instala aparte como `.dpkg-dist` o `.rpmnew`.

=== "Docker"

    ```bash
    docker pull ghcr.io/vsc55/storageweb:X.Y.Z
    docker rm -f storageweb && docker run ... ghcr.io/vsc55/storageweb:X.Y.Z
    ```

=== "Gentoo"

    Descomprime el overlay nuevo sobre el anterior y ejecuta `emerge -u www-apps/storageweb`.

=== "Desde el código"

    ```bash
    git pull     # o descomprime el nuevo .tar.gz
    sudo ./packaging/install.sh
    ```

## Migraciones de la base de datos

Se aplican solas al arrancar, o con `storageweb-admin init-db`, en orden y cada una en una transacción. El log muestra `Migraciones aplicadas: 002, …`.

**Volver a una versión anterior** no deshace las migraciones. Si una actualización sale mal, restaura la copia que hiciste antes de actualizar, con la versión anterior instalada ([Restaurar desde la línea de comandos](copias-seguridad.md#restaurar-desde-la-linea-de-comandos)).

## Versionado

StorageWeb sigue [versionado semántico](https://semver.org/lang/es/):

- **parche** (`1.2.3` → `1.2.4`): correcciones;
- **menor** (`1.2` → `1.3`): funcionalidades compatibles;
- **mayor** (`1.x` → `2.0`): puede haber cambios incompatibles en la configuración, la CLI o la API, siempre documentados en el changelog.

# 0014. Almacenamiento externo: backends por raíz

- **Estado:** Aceptada
- **Fecha:** 2026-11-14

## Contexto

Todos los archivos estaban en el disco del servidor: cada raíz (carpeta personal o compartida) era una ruta y el código trabajaba con `pathlib` directamente (`resolve_inside`, `os.replace`, `send_file`). Se pidió poder usar almacenamiento externo (NFS, SMB, S3…).

- NFS, SMB/CIFS o rclone se pueden montar en el sistema y ya funcionaban como una ruta más.
- Montar no siempre es posible: contenedores sin privilegios, Windows, o almacenamiento de objetos (S3) que no es un sistema de ficheros.

## Decisión

- **Un backend por raíz** (`core/backends/`): `LocalBackend` y uno por tipo de ubicación (`S3Backend`, `SMBBackend` y, después, `SFTPBackend`, `WebDAVBackend`, `FTPBackend` y `AzureBlobBackend`), con la misma interfaz (`stat`, `listdir`, `open`, `mkdir`, `rename`, `delete`, `store`, `ensure_root`, `check`). `core/storage.available_roots` añade el backend a cada raíz y el resto del código usa **rutas relativas POSIX** (`clean_rel`), sin saber dónde están los archivos.
- **Tipos que se descubren solos**: cada tipo es una subclase de `RemoteBackend` en su fichero (`core/backends/s3.py`, `smb.py`) que declara su **esquema** (`settings.location_types.LocationSchema`: etiquetas, opciones con su clase —texto, ruta, URL, secreto, booleano, puerto—, obligatorias, ayuda y documentación) e implementa `connect`, `create` y `address`. `core.backends.discover()` recorre el paquete al importar `core` y registra cada tipo; el esquema queda en `settings.location_types`, que es de lo que tiran el cargador (validación y ocultar secretos), las páginas de la administración (formulario genérico) y `tools/gen_docs.py` (una tabla por tipo). Así `settings` no depende de `core` y un tipo nuevo es un fichero nuevo, sin tocar código general.
- **Ubicaciones con nombre** (`storage.locations`): la conexión (bucket, servidor, credenciales) se define una vez. Las carpetas compartidas (`shares[].location`) y las personales (`storage.home_location`) la eligen y ponen una ruta relativa dentro. Sin ubicación, todo sigue como antes: ruta en el disco.
- **Montajes sin cambios**: siguen siendo la opción recomendada cuando se puede montar; no necesitan ubicación.
- **Subidas por partes en local**: el `.part` se guarda en la zona local del backend. En el disco es junto al destino (renombrado atómico al terminar, como antes); en S3 y SMB es `<data_dir>/uploads` y al terminar se envía con `store`. Así la reanudación ([0006](0006-subidas-por-partes.md)) no depende del almacenamiento remoto.
- **Descargas en streaming**: en el disco, `send_file` con la ruta; en remoto, un fichero con `seek` (`S3Reader` pide `Range` desde la posición; `smbclient` ya lo tiene) y `make_conditional` con el tamaño conocido, de modo que `Range` sigue funcionando.
- **Dependencias opcionales**: `boto3` (`[s3]`), `smbprotocol` (`[smb]`), `paramiko` (`[sftp]`) y `azure-storage-blob` (`[azure]`), importadas solo al usar una ubicación de ese tipo; WebDAV y FTP usan la biblioteca estándar. La imagen Docker las incluye.
- **Lectura con `seek` común** (`RangedReader`): pide al servidor desde la posición actual (`Range` en S3, WebDAV y Azure; `REST` en FTP). SFTP y SMB ya tienen ficheros con `seek`.
- **Fallos aislados**: si un backend no se puede crear (falta la biblioteca, la ubicación no existe o no conecta), la raíz recibe un `UnavailableBackend` que da el motivo en cada operación; el resto de carpetas siguen funcionando.

## Alternativas consideradas

- **Solo documentar montajes:** no cubre S3 ni los entornos donde no se puede montar.
- **fsspec / PyFilesystem2:** una capa genérica con muchos backends, pero con dependencias pesadas, semánticas distintas por backend (directorios en S3, errores) y poco control sobre `Range` y las subidas por partes. Nuestra interfaz es pequeña y la cubren dos implementaciones de unas 200 líneas.
- **Subida multiparte directa a S3 desde las partes del navegador:** ahorra el disco local, pero el tamaño mínimo de parte de S3 (5 MB), la reanudación y SMB (sin equivalente) complicarían el protocolo de subida. Se puede añadir más adelante sin cambiar la API.
- **Tipos fijos en el código general** (una lista de campos por tipo en `settings/defaults.py` y plantillas con `if s3 / smb`): fue la primera versión. Cada tipo nuevo obligaba a tocar el cargador, la web y la documentación.
- **Entry points de Python** (`[project.entry-points]`) para descubrir tipos de otros paquetes: más flexible, pero obliga a reinstalar el paquete al añadir uno. `backends.register()` deja la puerta abierta si algún día hace falta.
- **Credenciales en un almacén aparte:** no hay otro almacén en el proyecto; se tratan como el `client_secret` de Entra ID (base de datos o `config.json`, ocultos en la web y en `check-config`).

## Consecuencias

- Renombrar o borrar carpetas grandes en S3 es lento (copiar y borrar objeto a objeto).
- `<data_dir>/uploads` necesita espacio para las subidas en curso hacia ubicaciones remotas.
- Los tests usan clientes falsos (`tests/fakes.py`) que se inyectan con `backends.CLIENT_FACTORIES`, y todos los tipos pasan la misma batería (`tests/unit/test_backends.py`). En el CI no hay servidores reales; en el desarrollo se probaron FTP, FTPS, WebDAV, SFTP y S3 contra servidores locales (pyftpdlib, wsgidav, paramiko y moto). Azure y SMB solo con clientes falsos.
- Una raíz ya no tiene siempre `path` (`None` si es remota). El código que necesite la ruta en disco debe usar `backend.local_path()`.

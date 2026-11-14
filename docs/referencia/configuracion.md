<!-- Generado por tools/gen_docs.py: no editar a mano -->

# Referencia de configuración

Todas las opciones, con su valor por defecto y su variable de entorno. Las rutas relativas se resuelven respecto a la carpeta donde está el `config.json`.

Cada valor sale de la capa con más prioridad que lo fije, campo a campo: **predeterminado** < **ajustes web** < **`config.json`** < **variable de entorno**. Lo que fijan `config.json` o una variable queda bloqueado en la web.

- **Web**: «Sí» = se puede cambiar desde las páginas de la administración (se aplica al momento) si no lo fijan `config.json` ni el entorno. «No» = de arranque: solo `config.json` o el entorno, y requiere reiniciar el servicio.
- **Variable**: `STORAGEWEB_` + la ruta en mayúsculas con `__` entre niveles. Las listas y los objetos van en JSON (las listas de texto también separadas por comas); los booleanos, `true`/`false`.
- Los valores secretos nunca se muestran en la web.

## General

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `app_name` | texto | `"StorageWeb"` | Sí | `STORAGEWEB_APP_NAME` | Nombre que se muestra en la cabecera y en el título de las páginas. |
| `default_locale` | texto | `"en"` | Sí | `STORAGEWEB_DEFAULT_LOCALE` | Idioma por defecto de la interfaz (`en` o `es`) cuando el usuario no ha elegido uno y el navegador no indica ninguno disponible. |
| `secret_key` | texto | `""` | No | `STORAGEWEB_SECRET_KEY` | Clave para firmar las cookies de sesión. Vacía = se genera y guarda en `<data_dir>/secret_key`. |
| `data_dir` | texto | `"data"` | No | `STORAGEWEB_DATA_DIR` | Carpeta de datos del servicio (base de datos, `secret_key`, copias de seguridad). |
| `database` | texto | `""` | No | `STORAGEWEB_DATABASE` | Ruta del fichero SQLite. Vacía = `<data_dir>/storageweb.db`. |
| `settings_profile` | texto | `"default"` | No | `STORAGEWEB_SETTINGS_PROFILE` | Perfil de ajustes web: nombre del juego de ajustes guardados en la base de datos que usa esta instancia (letras, números, `_` y `-`). Varias instancias pueden compartir base de datos con ajustes distintos. |

## Servidor (`server`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `server.host` | texto | `"127.0.0.1"` | No | `STORAGEWEB_SERVER__HOST` | Dirección en la que escucha el servidor. Con un proxy inverso delante, `127.0.0.1`. |
| `server.port` | entero | `8080` | No | `STORAGEWEB_SERVER__PORT`<br>`STORAGEWEB_PORT` | Puerto TCP de escucha. |
| `server.threads` | entero | `8` | No | `STORAGEWEB_SERVER__THREADS` | Hilos de Waitress para atender peticiones en paralelo. |
| `server.behind_proxy` | booleano | `true` | No | `STORAGEWEB_SERVER__BEHIND_PROXY`<br>`STORAGEWEB_BEHIND_PROXY` | Confiar en las cabeceras `X-Forwarded-*` (IP real, HTTPS, host) de un proxy inverso. Actívalo solo si hay un proxy delante. |
| `server.proxy_hops` | entero | `1` | No | `STORAGEWEB_SERVER__PROXY_HOPS`<br>`STORAGEWEB_PROXY_HOPS` | Número de proxies inversos encadenados delante del servicio (nginx = `1`; una CDN o un balanceador más nginx = `2`). Se confía en ese número de valores de `X-Forwarded-*`, incluido `X-Forwarded-Prefix` para servir bajo una subruta. |
| `server.max_upload_mb` | entero | `2048` | No | `STORAGEWEB_SERVER__MAX_UPLOAD_MB`<br>`STORAGEWEB_MAX_UPLOAD_MB` | Tamaño máximo de cada petición HTTP: cada parte de una subida y la subida clásica sin JavaScript. No limita el tamaño de los archivos (ver `storage.max_file_size_mb`). |

## Red (`network`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `network.public_url` | texto | `""` | Sí | `STORAGEWEB_NETWORK__PUBLIC_URL`<br>`STORAGEWEB_PUBLIC_URL` | Nombre público (FQDN) por el que entran los usuarios: `files.empresa.es`, con puerto o subruta si hace falta (`files.empresa.es/archivos`). Se asume HTTPS; escribe `http://` delante solo para pruebas en local. Se usa para las URLs externas: la de vuelta de Entra ID (si `auth.entra.redirect_uri` está vacía) y la de salida. Vacío = el host de cada petición. Se puede cambiar desde la web. |

## Sesión (`session`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `session.lifetime_hours` | entero | `8` | No | `STORAGEWEB_SESSION__LIFETIME_HOURS` | Duración de la sesión iniciada, en horas. |
| `session.cookie_secure` | booleano | `true` | No | `STORAGEWEB_SESSION__COOKIE_SECURE`<br>`STORAGEWEB_COOKIE_SECURE` | Enviar la cookie de sesión solo por HTTPS. Debe ser `true` en producción; `false` solo para pruebas en `http://localhost`. |

## Almacenamiento (`storage`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `storage.home_template` | texto | `"data/homes/{username}"` | Sí | `STORAGEWEB_STORAGE__HOME_TEMPLATE` | Ruta de la carpeta personal. Debe contener `{username}`, que se sustituye por el nombre de usuario saneado. |
| `storage.create_home` | booleano | `true` | Sí | `STORAGEWEB_STORAGE__CREATE_HOME` | Crear la carpeta personal en el primer acceso del usuario. |
| `storage.create_shares` | booleano | `false` | Sí | `STORAGEWEB_STORAGE__CREATE_SHARES` | Crear las carpetas compartidas si no existen (útil en desarrollo y Docker). |
| `storage.show_hidden` | booleano | `false` | Sí | `STORAGEWEB_STORAGE__SHOW_HIDDEN` | Mostrar archivos y carpetas que empiezan por punto. |
| `storage.max_file_size_mb` | entero | `0` | Sí | `STORAGEWEB_STORAGE__MAX_FILE_SIZE_MB` | Tamaño máximo por archivo en MB; `0` = sin límite. |
| `storage.shares` | lista | `[]` | Sí | `STORAGEWEB_STORAGE__SHARES` | Lista de carpetas compartidas (ver los campos de cada elemento abajo). |
| `storage.shares[].name` | | | Sí | | Identificador en la URL (`/f/<name>/`): letras, números, `_` y `-`. `home` está reservado. |
| `storage.shares[].label` | | | Sí | | Nombre visible. Por defecto, `name`. |
| `storage.shares[].location` | | | Sí | | Ubicación de `storage.locations` donde está la carpeta (S3, SMB). Vacía = el disco del servidor (también lo montado en él: NFS, SMB/CIFS…). |
| `storage.shares[].path` | | | Sí | | En el disco: ruta en el servidor (relativa = respecto a la carpeta del `config.json`). En una ubicación: ruta dentro de ella (vacía = su raíz). |
| `storage.shares[].read_only` | | | Sí | | Solo lectura: únicamente se permite descargar, también a los administradores. |
| `storage.shares[].users` | | | Sí | | Usuarios con acceso; `["*"]` = todos. |
| `storage.shares[].read_only_users` | | | Sí | | Usuarios de `users` que solo pueden leer; `"*"` = todos los que entran por `["*"]`. Quien entra también por un grupo con escritura puede escribir. |
| `storage.shares[].groups` | | | Sí | | Grupos con acceso: identificador de un grupo de *Personas → Grupos*, grupo del sistema, u Object ID/App Role de Entra ID. |
| `storage.shares[].read_only_groups` | | | Sí | | Grupos de `groups` que solo pueden leer (los edita la matriz de accesos). Quien entra también por otro grupo o por `users` con escritura puede escribir. |
| `storage.locations` | lista | `[]` | Sí | `STORAGEWEB_STORAGE__LOCATIONS` | Almacenamientos externos con nombre, que eligen las carpetas (ver *Tipos de ubicación*, abajo). |
| `storage.locations[].name` | | | Sí | | Identificador: letras, números, `_` y `-`. |
| `storage.locations[].label` | | | Sí | | Nombre visible. Por defecto, `name`. |
| `storage.locations[].type` | | | Sí | | Tipo de almacenamiento; sus opciones, en la tabla de su tipo (abajo). |
| `storage.home_location` | texto | `""` | Sí | `STORAGEWEB_STORAGE__HOME_LOCATION` | Ubicación de `storage.locations` donde están las carpetas personales. Vacía = el disco del servidor; con una ubicación, `home_template` es una ruta dentro de ella (`homes/{username}`). |

## Permisos (`permissions`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `permissions.user.upload` | booleano | `true` | Sí | `STORAGEWEB_PERMISSIONS__USER__UPLOAD` | El rol `user` puede subir archivos. |
| `permissions.user.download` | booleano | `true` | Sí | `STORAGEWEB_PERMISSIONS__USER__DOWNLOAD` | El rol `user` puede descargar archivos. |
| `permissions.user.mkdir` | booleano | `true` | Sí | `STORAGEWEB_PERMISSIONS__USER__MKDIR` | El rol `user` puede crear carpetas. |
| `permissions.user.rename` | booleano | `false` | Sí | `STORAGEWEB_PERMISSIONS__USER__RENAME` | El rol `user` puede renombrar archivos y carpetas. |
| `permissions.user.delete` | booleano | `false` | Sí | `STORAGEWEB_PERMISSIONS__USER__DELETE` | El rol `user` puede eliminar archivos y carpetas. |

## Autenticación (`auth`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `auth.local.enabled` | booleano | `true` | Sí | `STORAGEWEB_AUTH__LOCAL__ENABLED` | Permitir el inicio de sesión de usuarios locales (guardados en SQLite). |
| `auth.pam.enabled` | booleano | `false` | Sí | `STORAGEWEB_AUTH__PAM__ENABLED` | Permitir el inicio de sesión de usuarios del sistema operativo mediante PAM (Linux/macOS). |
| `auth.pam.service` | texto | `"login"` | Sí | `STORAGEWEB_AUTH__PAM__SERVICE` | Servicio PAM que se usa para autenticar. |
| `auth.pam.allowed_groups` | lista | `[]` | Sí | `STORAGEWEB_AUTH__PAM__ALLOWED_GROUPS` | Si no está vacío, solo entran los miembros de estos grupos del sistema. |
| `auth.pam.admin_groups` | lista | `[]` | Sí | `STORAGEWEB_AUTH__PAM__ADMIN_GROUPS` | Los miembros de estos grupos del sistema reciben el rol `admin`. |
| `auth.pam.use_system_home` | booleano | `false` | Sí | `STORAGEWEB_AUTH__PAM__USE_SYSTEM_HOME` | Usar el home real del usuario (`/home/<usuario>`) en vez de `storage.home_template`. |
| `auth.entra.enabled` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__ENABLED` | Activar el inicio de sesión con Microsoft Entra ID. |
| `auth.entra.provider` | texto | `"oauth2"` | Sí | `STORAGEWEB_AUTH__ENTRA__PROVIDER` | Implementación: `oauth2` (propia, sin descubrimiento por red) o `msal` (librería de Microsoft). |
| `auth.entra.tenant_id` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__TENANT_ID` | Directory (tenant) ID. También admite `organizations` o `common` (multi-tenant). |
| `auth.entra.client_id` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__CLIENT_ID` | Application (client) ID del registro de aplicación. |
| `auth.entra.client_secret` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__CLIENT_SECRET` | Secreto del registro de aplicación. Nunca se muestra en la web. |
| `auth.entra.redirect_uri` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__REDIRECT_URI` | URL de vuelta registrada en Entra ID, p. ej. `https://files.midominio.com/auth/entra/callback`. Vacía = se calcula a partir de la petición. |
| `auth.entra.scopes` | lista | `["User.Read"]` | Sí | `STORAGEWEB_AUTH__ENTRA__SCOPES` | Scopes adicionales a `openid profile email`. |
| `auth.entra.button_label` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__BUTTON_LABEL` | Texto del botón de inicio de sesión. Vacío = texto por defecto en el idioma del usuario. |
| `auth.entra.username_claim` | texto | `"preferred_username"` | Sí | `STORAGEWEB_AUTH__ENTRA__USERNAME_CLAIM` | Claim del id_token que se usa como nombre de usuario. |
| `auth.entra.strip_domain` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__STRIP_DOMAIN` | Quitar el dominio del nombre de usuario (`juan@contoso.com` → `juan`). Cuidado con las colisiones con usuarios locales. |
| `auth.entra.allowed_groups` | lista | `[]` | Sí | `STORAGEWEB_AUTH__ENTRA__ALLOWED_GROUPS` | Grupos (Object ID) o App Roles permitidos; vacío = cualquier usuario del tenant. |
| `auth.entra.auto_provision` | booleano | `true` | Sí | `STORAGEWEB_AUTH__ENTRA__AUTO_PROVISION` | Crear el usuario automáticamente en su primer inicio de sesión. Si es `false`, solo entran los usuarios dados de alta antes por un administrador. |
| `auth.entra.default_role` | texto | `"user"` | Sí | `STORAGEWEB_AUTH__ENTRA__DEFAULT_ROLE` | Rol de los usuarios nuevos cuando no aplica ningún mapeo (`user` o `admin`). |
| `auth.entra.role_mappings` | objeto | `{}` | Sí | `STORAGEWEB_AUTH__ENTRA__ROLE_MAPPINGS` | Grupo (Object ID) o App Role → rol, p. ej. `{"StorageWeb.Admin": "admin"}`. Si coinciden varios, gana `admin`. |
| `auth.entra.sync_role_on_login` | booleano | `true` | Sí | `STORAGEWEB_AUTH__ENTRA__SYNC_ROLE_ON_LOGIN` | Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión. |
| `auth.entra.single_logout` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__SINGLE_LOGOUT` | Cerrar también la sesión de Microsoft al salir. |
| `auth.entra.authorize_url` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__AUTHORIZE_URL` | Solo `oauth2`: endpoint de autorización propio (nubes soberanas u otro proveedor OIDC). |
| `auth.entra.token_url` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__TOKEN_URL` | Solo `oauth2`: endpoint de token propio. |
| `auth.entra.issuer` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__ISSUER` | Solo `oauth2`: valor esperado del claim `iss`. |
| `auth.entra.logout_url` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__LOGOUT_URL` | Endpoint de cierre de sesión propio. |
| `auth.entra.timeout_seconds` | entero | `15` | Sí | `STORAGEWEB_AUTH__ENTRA__TIMEOUT_SECONDS` | Tiempo máximo de espera al endpoint de token, en segundos. |
| `auth.entra.secret_expires` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__SECRET_EXPIRES` | Fecha de caducidad del `client_secret` (ISO 8601). La rellenan el registro automático y la renovación; con ella se avisa a los admins 30 días antes. |

## Seguridad (`security`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `security.max_login_failures` | entero | `5` | Sí | `STORAGEWEB_SECURITY__MAX_LOGIN_FAILURES` | Intentos fallidos (por IP o por usuario) antes de bloquear temporalmente el login. |
| `security.lockout_minutes` | entero | `15` | Sí | `STORAGEWEB_SECURITY__LOCKOUT_MINUTES` | Duración del bloqueo tras demasiados intentos fallidos, en minutos. |
| `security.ipban_enabled` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__IPBAN_ENABLED` | Bloquear automáticamente las IPs con muchas infracciones (contraseñas erróneas, CSRF no válido, tokens de API no válidos). Las direcciones de loopback y las de la lista blanca nunca se bloquean. |
| `security.ipban_threshold` | entero | `20` | Sí | `STORAGEWEB_SECURITY__IPBAN_THRESHOLD` | Infracciones que bloquean una IP. |
| `security.ipban_window_minutes` | entero | `10` | Sí | `STORAGEWEB_SECURITY__IPBAN_WINDOW_MINUTES` | Ventana en la que se cuentan las infracciones, en minutos. |
| `security.ipban_minutes` | entero | `60` | Sí | `STORAGEWEB_SECURITY__IPBAN_MINUTES` | Duración del bloqueo automático, en minutos; `0` = hasta que un admin lo quite. |
| `security.api_tokens` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__API_TOKENS` | Permitir tokens de API personales (`Authorization: Bearer sw_…`) para scripts. |

## Mantenimiento (`maintenance`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `maintenance.audit_retention_days` | entero | `0` | Sí | `STORAGEWEB_MAINTENANCE__AUDIT_RETENTION_DAYS` | Días que se conserva la auditoría; `0` = siempre. La limpieza se hace una vez al día. |
| `maintenance.backup_interval_hours` | entero | `0` | Sí | `STORAGEWEB_MAINTENANCE__BACKUP_INTERVAL_HOURS` | Cada cuántas horas hace el servicio una copia de seguridad en `<data_dir>/backups`; `0` = nunca (puedes usar el timer de systemd). |
| `maintenance.backup_keep` | entero | `7` | Sí | `STORAGEWEB_MAINTENANCE__BACKUP_KEEP` | Copias que se conservan en `<data_dir>/backups`; las más antiguas se borran. |

## Marca (`branding`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `branding.primary_color` | texto | `""` | Sí | `STORAGEWEB_BRANDING__PRIMARY_COLOR` | Color principal de la interfaz (`#rrggbb`). Vacío = el de serie. |
| `branding.logo` | texto | `""` | Sí | `STORAGEWEB_BRANDING__LOGO` | Logo propio: lo rellena la subida desde *Sistema → General y marca* (`logo.png`, `logo.svg`…). |

## Tipos de ubicación (`storage.locations[].type`)

Cada tipo lo declara su backend en `src/storageweb/core/backends/<tipo>.py`. Además de `name`, `label` y `type`, cada ubicación lleva las opciones de su tipo. Los secretos nunca se muestran en la web.

### `azure`: Azure

Contenedor de Azure Blob Storage. Requiere `pip install 'storageweb[azure]'`.

| Opción | Tipo | Por defecto | Obligatoria | Descripción |
|---|---|---|---|---|
| `account` | texto |  | Sí | Nombre de la cuenta de almacenamiento. |
| `container` | texto |  | Sí | Contenedor. |
| `prefix` | ruta relativa |  |  | Carpeta dentro del contenedor donde va todo (vacío = el contenedor). |
| `endpoint` | URL |  |  | Dirección del servicio si no es la pública de Azure (Azurite, nubes soberanas). |
| `account_key` | texto (secreto) |  |  | Clave de la cuenta (secreto). |
| `sas_token` | texto (secreto) |  |  | Token SAS del contenedor, en lugar de la clave (secreto). |

### `ftp`: FTP

Servidor FTP o FTPS (FTP con TLS). Sin dependencias.

| Opción | Tipo | Por defecto | Obligatoria | Descripción |
|---|---|---|---|---|
| `host` | texto |  | Sí | Nombre o IP del servidor. |
| `port` | puerto | `21` |  | Puerto (`21`). |
| `path` | ruta en el servidor |  |  | Carpeta del servidor donde va todo: absoluta (`/datos`) o relativa a la del usuario. |
| `tls` | booleano | `true` |  | Usar FTPS explícito (`AUTH TLS`): sesión y datos cifrados. |
| `verify_tls` | booleano | `true` |  | Comprobar el certificado TLS del servidor. Desactívalo solo con certificados propios. |
| `username` | texto |  |  | Usuario (vacío = anónimo). |
| `password` | texto (secreto) |  |  | Contraseña (secreto). |

### `s3`: S3

Amazon S3 o compatible (MinIO, Wasabi, Backblaze B2, Cloudflare R2…). Requiere `pip install 'storageweb[s3]'`.

| Opción | Tipo | Por defecto | Obligatoria | Descripción |
|---|---|---|---|---|
| `bucket` | texto |  | Sí | Nombre del bucket. |
| `prefix` | ruta relativa |  |  | Prefijo dentro del bucket donde va todo (vacío = todo el bucket). |
| `region` | texto |  |  | Región (`eu-west-1`…). Vacía = la del entorno. |
| `endpoint_url` | URL |  |  | URL del servicio si no es AWS (MinIO, Wasabi, R2…): `https://s3.ejemplo.com`. |
| `path_style` | booleano |  |  | Direcciones `https://servidor/bucket` en vez de `https://bucket.servidor` (MinIO). |
| `access_key` | texto |  |  | Access Key ID. Vacía = credenciales del entorno. |
| `secret_key` | texto (secreto) |  |  | Secret Access Key (secreto: nunca se muestra en la web). |

### `sftp`: SFTP

Servidor SFTP (SSH): Linux, NAS, hostings. Requiere `pip install 'storageweb[sftp]'`.

| Opción | Tipo | Por defecto | Obligatoria | Descripción |
|---|---|---|---|---|
| `host` | texto |  | Sí | Nombre o IP del servidor. |
| `port` | puerto | `22` |  | Puerto SSH (`22`). |
| `path` | ruta en el servidor |  |  | Carpeta del servidor donde va todo: absoluta (`/srv/datos`) o relativa a la del usuario. |
| `host_key` | texto |  |  | Clave pública del servidor (línea de `ssh-keyscan`) o su huella `SHA256:…`. Vacía = se acepta cualquiera (no recomendado). |
| `username` | texto |  | Sí | Usuario. |
| `password` | texto (secreto) |  |  | Contraseña, o la frase de la clave privada (secreto). |
| `private_key` | texto de varias líneas (secreto) |  |  | Clave privada (OpenSSH o PEM). Secreta. |

### `smb`: SMB

Recurso compartido de Windows, Samba o un NAS, sin montarlo en el sistema. Requiere `pip install 'storageweb[smb]'`.

| Opción | Tipo | Por defecto | Obligatoria | Descripción |
|---|---|---|---|---|
| `server` | texto |  | Sí | Nombre o IP del servidor. |
| `port` | puerto | `445` |  | Puerto (`445`). |
| `share` | texto |  | Sí | Recurso compartido (`datos` en `\\nas\datos`). |
| `path` | ruta relativa |  |  | Carpeta dentro del recurso donde va todo (vacía = su raíz). |
| `encrypt` | booleano | `true` |  | Exigir cifrado SMB 3. |
| `username` | texto |  |  | Usuario (`DOMINIO\usuario` o `usuario@dominio`). |
| `password` | texto (secreto) |  |  | Contraseña (secreto: nunca se muestra en la web). |

### `webdav`: WebDAV

Servidor WebDAV (Nextcloud, ownCloud, SharePoint, NAS). Sin dependencias.

| Opción | Tipo | Por defecto | Obligatoria | Descripción |
|---|---|---|---|---|
| `url` | URL |  | Sí | Dirección WebDAV. Nextcloud: `https://servidor/remote.php/dav/files/<usuario>/`. |
| `path` | ruta relativa |  |  | Carpeta dentro de esa dirección donde va todo (vacía = su raíz). |
| `verify_tls` | booleano | `true` |  | Comprobar el certificado TLS del servidor. Desactívalo solo con certificados propios. |
| `username` | texto |  |  | Usuario. |
| `password` | texto (secreto) |  |  | Contraseña o contraseña de aplicación (secreto). |

## Ejemplo

El fichero `config/config.example.json` del repositorio (instalado en `/etc/storageweb/config.json` por los paquetes) solo trae lo de arranque y la plantilla de las carpetas personales: así lo demás se puede cambiar desde la web.

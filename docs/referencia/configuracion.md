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
| `network.public_url` | texto | `""` | Sí | `STORAGEWEB_NETWORK__PUBLIC_URL`<br>`STORAGEWEB_PUBLIC_URL` | Nombre público (FQDN) por el que entran los usuarios: `files.empresa.es`, con puerto o subruta si hace falta (`files.empresa.es/archivos`). Se asume HTTPS; escribe `http://` delante solo para pruebas en local. Se usa para las URLs externas: la de vuelta de Entra ID (`/auth/entra/callback`, que nunca se guarda: se calcula siempre de aquí) y la de salida. Vacío = la dirección con la que entra el navegador (su host y puerto). Se puede cambiar desde la web. |

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
| `storage.show_hidden` | booleano | `false` | Sí | `STORAGEWEB_STORAGE__SHOW_HIDDEN` | Mostrar en la web los archivos y carpetas que empiezan por punto. La unidad de red (WebDAV) los muestra siempre. |
| `storage.page_size` | entero | `200` | Sí | `STORAGEWEB_STORAGE__PAGE_SIZE` | Elementos de una carpeta que el explorador muestra de una vez (de 50 a 5000). Las carpetas con más se ven según `storage.listing_mode`. La API y la unidad de red siempre listan la carpeta entera. |
| `storage.listing_mode` | texto | `"scroll"` | Sí | `STORAGEWEB_STORAGE__LISTING_MODE` | Cómo se ve una carpeta con más de `storage.page_size` elementos: `scroll` (se cargan más al bajar), `pages` (por páginas, con *Anterior* y *Siguiente*) o `search` (solo los primeros; el resto, con el filtro). En los tres, el filtro de la carpeta busca entre todos sus elementos. |
| `storage.hidden` | lista | `[]` | Sí | `STORAGEWEB_STORAGE__HIDDEN` | Archivos y carpetas **ocultos para todos**: no se listan ni se pueden abrir ni crear, ni en la web ni por WebDAV ni por la API (la extensión de VS Code tampoco los sincroniza). Patrones como los de `.gitignore`, sobre la ruta dentro de cada carpeta: `Thumbs.db`, `*.tmp` (en cualquier sitio), `.git/` (solo carpetas), `/privado` (desde la raíz). Los archivos siguen en el disco. Es para no mostrar cosas (basura del sistema, carpetas técnicas), no un control de acceso: para eso, los permisos de las carpetas. La lista no se envía a los clientes. |
| `storage.max_file_size_mb` | entero | `0` | Sí | `STORAGEWEB_STORAGE__MAX_FILE_SIZE_MB` | Tamaño máximo por archivo en MB; `0` = sin límite. |
| `storage.home_quota_mb` | entero | `0` | Sí | `STORAGEWEB_STORAGE__HOME_QUOTA_MB` | Cuota por defecto de las **carpetas personales**, en MB; `0` = sin cuota. Cada usuario puede tener otra en su ficha, y cada grupo una para sus miembros (`storage.group_quotas`). |
| `storage.group_quotas` | objeto | `{}` | Sí | `STORAGEWEB_STORAGE__GROUP_QUOTAS` | Cuota de la carpeta personal de los miembros de cada grupo, en MB: `{"rrhh": 5120}`. Si alguien está en varios, la mayor (`0` = sin cuota gana). La del propio usuario manda sobre la de sus grupos. Se edita en la ficha de cada grupo (se guarda en el grupo); la de un grupo puesta aquí en config.json no se puede cambiar desde la web. |
| `storage.quota_enforce` | booleano | `true` | Sí | `STORAGEWEB_STORAGE__QUOTA_ENFORCE` | Si las cuotas **impiden escribir**: lo que no quepa no se puede subir, copiar ni mover (web, API y unidad de red responden 507). `false` = solo avisan (a partir del 90 % y al superarla). |
| `storage.quota_refresh_minutes` | entero | `60` | Sí | `STORAGEWEB_STORAGE__QUOTA_REFRESH_MINUTES` | Cada cuántos minutos se vuelve a medir **en segundo plano** el uso de una carpeta con cuota (de 1 a 10080). Lo que escribe o borra StorageWeb se cuenta al momento; esto recoge lo que otros cambien directamente en el almacenamiento (otro programa en el mismo bucket o NAS). Nunca se recorre una carpeta mientras alguien espera, salvo la primera vez desde que arranca el servicio. Una ubicación marcada como *No cuenta para la cuota* (`quota_exempt`) deja sin cuota las carpetas que estén en ella. |
| `storage.shares` | lista | `[]` | Sí | `STORAGEWEB_STORAGE__SHARES` | Lista de carpetas compartidas (ver los campos de cada elemento abajo). Las de config.json o del entorno se ven en la web de solo lectura, junto a las creadas desde la web (que se guardan en su propia tabla); si un nombre está en los dos sitios, manda config.json. |
| `storage.shares[].name` | | | Sí | | Identificador en la URL (`/f/<name>/`): letras, números, `_` y `-`. `home` está reservado. |
| `storage.shares[].label` | | | Sí | | Nombre visible. Por defecto, `name`. |
| `storage.shares[].location` | | | Sí | | Ubicación de `storage.locations` donde está la carpeta (S3, SMB). Vacía = el disco del servidor (también lo montado en él: NFS, SMB/CIFS…). |
| `storage.shares[].path` | | | Sí | | En el disco: ruta en el servidor (relativa = respecto a la carpeta del `config.json`). En una ubicación: ruta dentro de ella (vacía = su raíz). |
| `storage.shares[].read_only` | | | Sí | | Solo lectura: únicamente se permite descargar, también a los administradores. |
| `storage.shares[].quota_mb` | | | Sí | | Cuota de la carpeta compartida en MB; `0` o ausente = sin cuota. Solo avisa. |
| `storage.shares[].users` | | | Sí | | Usuarios con acceso; `["*"]` = todos. |
| `storage.shares[].read_only_users` | | | Sí | | Usuarios de `users` que solo pueden leer; `"*"` = todos los que entran por `["*"]`. Quien entra también por un grupo con escritura puede escribir. |
| `storage.shares[].groups` | | | Sí | | Grupos con acceso: identificador de un grupo de *Personas → Grupos*, grupo del sistema, u Object ID/App Role de Entra ID. |
| `storage.shares[].read_only_groups` | | | Sí | | Grupos de `groups` que solo pueden leer (los edita la matriz de accesos). Quien entra también por otro grupo o por `users` con escritura puede escribir. |
| `storage.locations` | lista | `[]` | Sí | `STORAGEWEB_STORAGE__LOCATIONS` | Almacenamientos externos con nombre, que eligen las carpetas (ver *Tipos de ubicación*, abajo). Los de config.json o del entorno se ven en la web de solo lectura, junto a los creados desde la web (que se guardan en su propia tabla). |
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
| `permissions.user.edit` | booleano | `false` | Sí | `STORAGEWEB_PERMISSIONS__USER__EDIT` | El rol `user` puede editar archivos de texto en el navegador (desde el visor). |

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
| `auth.entra.scopes` | lista | `["User.Read"]` | Sí | `STORAGEWEB_AUTH__ENTRA__SCOPES` | Scopes adicionales a `openid profile email`. |
| `auth.entra.button_label` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__BUTTON_LABEL` | Texto del botón de inicio de sesión. Vacío = texto por defecto en el idioma del usuario. |
| `auth.entra.username_claim` | texto | `"preferred_username"` | Sí | `STORAGEWEB_AUTH__ENTRA__USERNAME_CLAIM` | Claim del id_token que se usa como nombre de usuario. |
| `auth.entra.strip_domain` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__STRIP_DOMAIN` | Quitar el dominio del nombre de usuario (`juan@contoso.com` → `juan`). Cuidado con las colisiones con usuarios locales. |
| `auth.entra.allowed_groups` | lista | `[]` | Sí | `STORAGEWEB_AUTH__ENTRA__ALLOWED_GROUPS` | Grupos (Object ID) o App Roles permitidos; vacío = cualquier usuario del tenant. |
| `auth.entra.auto_provision` | booleano | `true` | Sí | `STORAGEWEB_AUTH__ENTRA__AUTO_PROVISION` | Crear el usuario automáticamente en su primer inicio de sesión. Si es `false`, solo entran los usuarios dados de alta antes por un administrador. |
| `auth.entra.default_role` | texto | `"user"` | Sí | `STORAGEWEB_AUTH__ENTRA__DEFAULT_ROLE` | Rol de los usuarios nuevos cuando no aplica ningún mapeo (`user` o `admin`). |
| `auth.entra.role_mappings` | objeto | `{}` | Sí | `STORAGEWEB_AUTH__ENTRA__ROLE_MAPPINGS` | Grupo (Object ID) o App Role → rol, p. ej. `{"StorageWeb.Admin": "admin"}`. Si coinciden varios, gana `admin`. |
| `auth.entra.sync_role_on_login` | booleano | `true` | Sí | `STORAGEWEB_AUTH__ENTRA__SYNC_ROLE_ON_LOGIN` | Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión. |
| `auth.entra.directory_sync_minutes` | entero | `60` | Sí | `STORAGEWEB_AUTH__ENTRA__DIRECTORY_SYNC_MINUTES` | Cada cuántos minutos se revisan contra Entra ID las cuentas que pueden entrar sin pasar por Microsoft (sesión abierta, tokens de API, unidad de red, extensión de VS Code): se desactivan las borradas, desactivadas o fuera de los grupos permitidos (y se reactivan solas al volver), y se actualizan sus grupos y su rol. Necesita el permiso de aplicación `User.Read.All`. `0` = solo al iniciar sesión. La revisión corre cada 10 minutos como mucho. |
| `auth.entra.single_logout` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__SINGLE_LOGOUT` | Cerrar también la sesión de Microsoft al salir. |
| `auth.entra.auto_login` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__AUTO_LOGIN` | Ir directamente a Microsoft sin mostrar la página de inicio de sesión. En equipos unidos a Entra ID (Intune) se entra sin escribir nada. `/login?manual=1` sigue mostrando la página (usuarios locales, rescate). |
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
| `security.api_token_max_days` | entero | `0` | Sí | `STORAGEWEB_SECURITY__API_TOKEN_MAX_DAYS` | Días como mucho que puede durar un token de API; `0` = sin límite (se pueden crear sin caducidad). Con un límite no se pueden crear sin caducidad ni más largos, al rotarlos o conectar una aplicación se recortan, y los que ya existen dejan de valer al cumplir ese tiempo desde que se crearon. |
| `security.webdav` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__WEBDAV` | Unidad de red: servidor WebDAV en `/dav/` (Windows, macOS, Linux, rclone…). Se entra con el nombre de usuario y un token de API como contraseña. Necesita `api_tokens` salvo que se admita la contraseña de la cuenta. |
| `security.webdav_passwords` | booleano | `false` | Sí | `STORAGEWEB_SECURITY__WEBDAV_PASSWORDS` | Admitir también la contraseña de la cuenta (usuarios locales y PAM) en WebDAV. Desactivado: solo tokens, que se pueden revocar y limitar a lectura. |
| `security.mfa_required` | texto | `"off"` | Sí | `STORAGEWEB_SECURITY__MFA_REQUIRED` | Quién debe tener la **verificación en dos pasos** (TOTP): `off` (nadie, quien quiera la activa en *Mi perfil*), `admins` (los administradores) o `all` (todas las cuentas). Solo las cuentas con contraseña (locales y PAM): quien entra con Microsoft Entra ID usa el segundo factor de Microsoft. Quien la debe y no la tiene la configura al iniciar sesión; quien la tiene la usa siempre, diga lo que diga esto. |

## preview

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `preview.enabled` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__ENABLED` | Abrir en el navegador, sin descargarlos, los archivos de texto y Markdown (doble clic en el explorador). Desactivado, todos se descargan como cualquier otro archivo. |
| `preview.diagrams` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__DIAGRAMS` | Dibujar los diagramas `mermaid` de los `.md` (con Mermaid, en un marco aislado del resto de la página). Desactivado, se ve su código y Mermaid no se descarga. |
| `preview.highlight` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__HIGHLIGHT` | Colorear el código (Python, PHP, JavaScript, SQL, YAML, PowerShell… y los bloques de código de los `.md`) con highlight.js. Desactivado, se ve sin colores y highlight.js no se descarga. Los archivos de más de 1 MB se ven siempre sin colores. |
| `preview.max_mb` | entero | `2` | Sí | `STORAGEWEB_PREVIEW__MAX_MB` | Tamaño máximo, en MB, de un archivo para verse en el navegador (de 1 a 20); más grande, se descarga. |
| `preview.extensions` | lista | `["adoc", "asm", "bash", "bat", "c", "cc", "cfg", "cjs", "cmake", "cmd", "conf", "config", "cpp", "cs", "css", "csv", "dart", "diff", "dockerfile", "editorconfig", "fish", "gitattributes", "gitignore", "go", "gradle", "graphql", "groovy", "h", "hcl", "hpp", "htm", "html", "ini", "java", "js", "json", "jsonl", "jsx", "kt", "kts", "less", "lock", "log", "lua", "m", "markdown", "md", "mdown", "mjs", "mk", "mkd", "mkdn", "ndjson", "nfo", "nix", "patch", "php", "pl", "pm", "properties", "proto", "ps1", "psd1", "psm1", "py", "pyw", "r", "rb", "reg", "rs", "rst", "s", "sass", "scala", "scss", "sh", "sql", "srt", "svelte", "svg", "swift", "tex", "text", "tf", "toml", "ts", "tsv", "tsx", "txt", "vb", "vbs", "vtt", "vue", "xhtml", "xml", "yaml", "yml", "zsh"]` | Sí | `STORAGEWEB_PREVIEW__EXTENSIONS` | Extensiones (sin el punto) que se abren en el visor: la lista entera. De serie, Markdown (`md`…, con formato), HTML y SVG (`html`, `svg`…, siempre como código), texto y datos (`txt`, `log`, `csv`, `json`, `yml`…) y código (`py`, `js`, `ps1`, `sh`, `sql`…). Si la cambias, se guarda la tuya entera; *Restablecer* vuelve a la de serie. Archivos como `README` o `Dockerfile` se abren siempre. |
| `preview.blocked_extensions` | lista | `["asc", "env", "key", "pem", "ppk"]` | Sí | `STORAGEWEB_PREVIEW__BLOCKED_EXTENSIONS` | Extensiones que nunca se abren en el visor, aunque estén en la lista anterior: se descargan. De serie, archivos de texto que suelen guardar secretos o claves: `asc`, `env`, `key`, `pem` y `ppk`. Un archivo sin extensión que empieza por punto cuenta como si lo fuera: `.env` se bloquea con `env`. |

## Mantenimiento (`maintenance`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `maintenance.audit_retention_days` | entero | `0` | Sí | `STORAGEWEB_MAINTENANCE__AUDIT_RETENTION_DAYS` | Días que se conserva la auditoría; `0` = siempre. La limpieza se hace una vez al día. |
| `maintenance.backup_interval_hours` | entero | `0` | Sí | `STORAGEWEB_MAINTENANCE__BACKUP_INTERVAL_HOURS` | Cada cuántas horas hace el servicio una copia de seguridad en `<data_dir>/backups`; `0` = nunca (puedes usar el timer de systemd). |
| `maintenance.backup_keep` | entero | `7` | Sí | `STORAGEWEB_MAINTENANCE__BACKUP_KEEP` | Copias que se conservan en `<data_dir>/backups`; las más antiguas se borran. |
| `maintenance.offsite_location` | texto | `""` | Sí | `STORAGEWEB_MAINTENANCE__OFFSITE_LOCATION` | Copia **fuera del servidor**: cada copia de seguridad (automática o desde la web) se envía también a esta [ubicación de almacenamiento](../administracion/almacenamiento.md) (S3, SMB, SFTP…); vacío = no. Si el servidor se pierde, desde *Copias y base de datos* de uno nuevo con la misma ubicación se traen y se restauran. |
| `maintenance.offsite_path` | texto | `"storageweb-backups"` | Sí | `STORAGEWEB_MAINTENANCE__OFFSITE_PATH` | Carpeta dentro de la ubicación donde se guardan las copias (se crea si no existe). |
| `maintenance.offsite_keep` | entero | `14` | Sí | `STORAGEWEB_MAINTENANCE__OFFSITE_KEEP` | Copias que se conservan en la ubicación; las más antiguas se borran (las de `antes-de-restaurar` y las subidas a mano, no). |

## audit

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `audit.min_level` | texto | `"debug"` | Sí | `STORAGEWEB_AUDIT__MIN_LEVEL` | Desde qué nivel se guarda cada evento en la auditoría: `debug` (todo: también listar carpetas, buscar, abrir en el visor, favoritos, tema e idioma), `info` (lo normal: entrar, subir, descargar, cambios), `warning` (intentos rechazados), `error` (fallos) o `critical` (incidentes de seguridad y cambios que no se deshacen). Ver los niveles de cada acción en la [referencia de la auditoría](auditoria.md). |
| `audit.forward_min_level` | texto | `"info"` | Sí | `STORAGEWEB_AUDIT__FORWARD_MIN_LEVEL` | Desde qué nivel se reenvía cada evento al syslog o al fichero JSON (`audit.syslog`, `audit.file`); por defecto, desde `info`: lo de `debug` se guarda aquí pero no llena el SIEM. |
| `audit.syslog` | texto | `""` | Sí | `STORAGEWEB_AUDIT__SYSLOG` | Reenviar cada evento de la auditoría a un **syslog o SIEM**: `udp://host:514`, `tcp://host:514` o `tls://host:6514` (RFC 5425); vacío = no. Se envía desde una cola en segundo plano: un colector lento o caído nunca frena el servicio (la auditoría sigue completa en la base de datos). |
| `audit.syslog_format` | texto | `"rfc5424"` | Sí | `STORAGEWEB_AUDIT__SYSLOG_FORMAT` | Formato del mensaje (siempre con cabecera RFC 5424): `rfc5424` (datos estructurados), `json` (el evento en JSON) o `cef` (Common Event Format: ArcSight, QRadar, Microsoft Sentinel). |
| `audit.syslog_facility` | texto | `"local0"` | Sí | `STORAGEWEB_AUDIT__SYSLOG_FACILITY` | Facilidad syslog: `local0` … `local7`, `auth`, `authpriv` o `user`. |
| `audit.syslog_ca` | texto | `""` | Sí | `STORAGEWEB_AUDIT__SYSLOG_CA` | Con `tls://`: fichero PEM con la CA del colector, si no la firma una de las del sistema. |
| `audit.tls_verify` | booleano | `true` | Sí | `STORAGEWEB_AUDIT__TLS_VERIFY` | Con `tls://`: comprobar el certificado del colector. Desactivarlo solo para pruebas. |
| `audit.file` | texto | `""` | Sí | `STORAGEWEB_AUDIT__FILE` | Escribir también cada evento en este fichero, uno en JSON por línea, para que lo lea un agente (Filebeat, Fluent Bit, Wazuh…); vacío = no. Se abre en cada escritura, así que se puede rotar con logrotate. |

## metrics

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `metrics.enabled` | booleano | `false` | Sí | `STORAGEWEB_METRICS__ENABLED` | Publicar métricas para Prometheus en `/metrics` (peticiones, subidas y descargas, inicios de sesión, IPs bloqueadas, espacio de las carpetas, ubicaciones remotas…). |
| `metrics.token` | texto | `""` | Sí | `STORAGEWEB_METRICS__TOKEN` | Token que tiene que enviar Prometheus (`Authorization: Bearer <token>`, `bearer_token` en su configuración); al menos 16 caracteres. Nunca se muestra en la web. |
| `metrics.allowed_networks` | lista | `[]` | Sí | `STORAGEWEB_METRICS__ALLOWED_NETWORKS` | IPs o redes (CIDR) desde las que se puede leer `/metrics` sin token. Sin token ni redes, solo desde el propio servidor. |

## Marca (`branding`)

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `branding.primary_color` | texto | `""` | Sí | `STORAGEWEB_BRANDING__PRIMARY_COLOR` | Color principal de la interfaz (`#rrggbb`). Vacío = el de serie. |
| `branding.logo` | texto | `""` | Sí | `STORAGEWEB_BRANDING__LOGO` | Logo propio: lo rellena la subida desde *Sistema → General y marca* (`logo.png`, `logo.svg`…). |
| `branding.login_art` | texto | `"classic"` | Sí | `STORAGEWEB_BRANDING__LOGIN_ART` | Ilustración de serie del lateral del inicio de sesión: `classic`, `sync` (sincronización), `waves` (ondas), `mosaic` (mosaico de archivos), `layers` (capas) o `random` (una distinta en cada carga). Toma el color principal. Una imagen propia (`branding.login_image`) manda sobre ella. |
| `branding.login_image` | texto | `""` | Sí | `STORAGEWEB_BRANDING__LOGIN_IMAGE` | Imagen del lateral del inicio de sesión: la rellena la subida desde *Sistema → General y marca* (`login.jpg`, `login.webp`…). Vacío = la ilustración de serie elegida (`branding.login_art`). |

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

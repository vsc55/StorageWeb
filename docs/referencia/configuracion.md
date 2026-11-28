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
| `storage.allowed_folders` | lista | `[]` | Sí | `STORAGEWEB_STORAGE__ALLOWED_FOLDERS` | Carpetas del disco del servidor que se pueden usar: las carpetas compartidas y personales que están en el disco (sin ubicación de almacenamiento) tienen que estar dentro de alguna, y el botón *Examinar* de la administración solo enseña lo que hay en ellas. Rutas absolutas (las relativas, respecto al config.json). Se compara la ruta real: un enlace simbólico que sale de ellas está fuera. Una carpeta que ya existía fuera deja de abrirse («no disponible») hasta que se mueva o se añada su carpeta. Vacío = cualquiera, salvo las rutas de red (`\\equipo\recurso`), que solo valen dentro de una de ellas. Para que solo lo cambie quien administra el servidor, póngase en el config.json o en una variable de entorno: así la web no lo puede ampliar. |
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
| `storage.quota_warn_percent` | entero | `90` | Sí | `STORAGEWEB_STORAGE__QUOTA_WARN_PERCENT` | Desde qué porcentaje de la cuota se avisa: la barra pasa a ámbar y el Resumen lo dice (de 50 a 99). |
| `storage.search_max_results` | entero | `200` | Sí | `STORAGEWEB_STORAGE__SEARCH_MAX_RESULTS` | La búsqueda por nombre (web y API) para al llegar a tantos resultados (de 10 a 5000) y lo dice. |
| `storage.search_seconds` | entero | `8` | Sí | `STORAGEWEB_STORAGE__SEARCH_SECONDS` | Segundos como mucho que dura una búsqueda por nombre (de 1 a 120); al cumplirlos para y enseña lo que lleva. En almacenamiento remoto recorrer carpetas es lento: súbelo si hace falta. |
| `storage.search_max_folders` | entero | `20000` | Sí | `STORAGEWEB_STORAGE__SEARCH_MAX_FOLDERS` | Carpetas como mucho que recorre una búsqueda por nombre (de 100 a 1 000 000). |
| `storage.upload_stale_hours` | entero | `24` | Sí | `STORAGEWEB_STORAGE__UPLOAD_STALE_HOURS` | Horas sin actividad tras las que se descarta una subida por partes a medias (de 1 a 720): hasta entonces se puede reanudar; después se borra su `.part`. |
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
| `permissions.user.share` | booleano | `false` | Sí | `STORAGEWEB_PERMISSIONS__USER__SHARE` | El rol `user` puede crear **enlaces para compartir** con gente de fuera (ver `sharing.*`). Apagado de serie. |
| `permissions.default_role` | texto | `"none"` | Sí | `STORAGEWEB_PERMISSIONS__DEFAULT_ROLE` | El rol de las **cuentas nuevas**: las que se dan de alta desde la web o con `storageweb-admin user-add` sin `--role`, las importadas y las que crea un método de inicio de sesión al entrar si el suyo (Entra ID: *Rol de los usuarios nuevos*) está vacío. `user`, `admin` o la clave de un rol propio (*Acceso → Roles*). Las cuentas que ya existen no cambian. |

## sharing

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `sharing.links` | booleano | `true` | Sí | `STORAGEWEB_SHARING__LINKS` | Enlaces para compartir un archivo o una carpeta con gente sin cuenta (`/s/<token>`): con caducidad, contraseña opcional y límite de descargas, o un **buzón** para que suban archivos. Los crea quien tenga el permiso *Compartir con enlaces* (los administradores siempre). Apagado, ninguno funciona (ni los ya creados) y no se pueden crear. |
| `sharing.default_days` | entero | `7` | Sí | `STORAGEWEB_SHARING__DEFAULT_DAYS` | Cuántos días dura un enlace si quien lo crea no elige otra cosa (de `1` a `3650`). |
| `sharing.max_days` | entero | `30` | Sí | `STORAGEWEB_SHARING__MAX_DAYS` | Lo máximo que puede durar un enlace, en días (de `0` a `3650`); `0` = sin máximo, y entonces se pueden crear enlaces que no caducan. |
| `sharing.require_password` | booleano | `false` | Sí | `STORAGEWEB_SHARING__REQUIRE_PASSWORD` | Exigir contraseña a todos los enlaces nuevos (los ya creados no cambian). |
| `sharing.upload_links` | booleano | `true` | Sí | `STORAGEWEB_SHARING__UPLOAD_LINKS` | Permitir **buzones**: enlaces a una carpeta para que alguien de fuera suba archivos sin ver lo que hay (necesitan además poder subir a esa carpeta). |
| `sharing.keep_days` | entero | `30` | Sí | `STORAGEWEB_SHARING__KEEP_DAYS` | Días que se conservan los enlaces **quitados o caducados** (siguen en la lista, con los filtros *Quitados* y *Caducados*) antes de que la limpieza diaria borre su fila; `0` = nunca se borran. Su historial no se borra con ellos: sigue `sharing.history_days` y se ve en el filtro *Borrados*. |
| `sharing.history_days` | entero | `0` | Sí | `STORAGEWEB_SHARING__HISTORY_DAYS` | Días que se conserva el **historial** de los enlaces (cada visita, descarga, subida, contraseña equivocada… con su IP y navegador); `0` = lo mismo que la auditoría (`maintenance.audit_retention_days`). Con un número, no puede ser menor que `sharing.keep_days`: un enlace no se queda sin su historial. |

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
| `auth.entra.default_role` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__DEFAULT_ROLE` | Rol de los usuarios nuevos cuando no aplica ningún mapeo: `user`, `admin` o la clave de un rol propio; vacío = el de las cuentas nuevas de StorageWeb (`permissions.default_role`). |
| `auth.entra.role_mappings` | objeto | `{}` | Sí | `STORAGEWEB_AUTH__ENTRA__ROLE_MAPPINGS` | Grupo (Object ID) o App Role → rol, p. ej. `{"StorageWeb.Admin": "admin"}`. Si coinciden varios, gana `admin`. |
| `auth.entra.sync_role_on_login` | booleano | `true` | Sí | `STORAGEWEB_AUTH__ENTRA__SYNC_ROLE_ON_LOGIN` | Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión. |
| `auth.entra.directory_sync_minutes` | entero | `60` | Sí | `STORAGEWEB_AUTH__ENTRA__DIRECTORY_SYNC_MINUTES` | Cada cuántos minutos se revisan contra Entra ID las cuentas que pueden entrar sin pasar por Microsoft (sesión abierta, tokens de API, unidad de red, extensión de VS Code): se desactivan las borradas, desactivadas o fuera de los grupos permitidos (y se reactivan solas al volver), y se actualizan sus grupos y su rol. Necesita el permiso de aplicación `User.Read.All`. `0` = solo al iniciar sesión. La revisión corre cada 10 minutos como mucho. |
| `auth.entra.single_logout` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__SINGLE_LOGOUT` | Cerrar también la sesión de Microsoft al salir. |
| `auth.entra.auto_login` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__AUTO_LOGIN` | Ir directamente a Microsoft sin mostrar la página de inicio de sesión. En equipos unidos a Entra ID (Intune) se entra sin escribir nada. `/login?manual=1` sigue mostrando la página (usuarios locales, rescate). |
| `auth.entra.desktop_sign_in` | booleano | `false` | Sí | `STORAGEWEB_AUTH__ENTRA__DESKTOP_SIGN_IN` | Dejar entrar a la extensión de VS Code con la cuenta de Windows (equipos unidos a Entra ID), sin navegador: VS Code pide a Windows un token de Microsoft para la API de StorageWeb y lo canjea por un token de API. La aplicación de Entra tiene que exponer la API `access_as_user` y autorizar a VS Code (el registro automático y *Reparar permisos* lo hacen). Solo la nube pública de Microsoft. |
| `auth.entra.authorize_url` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__AUTHORIZE_URL` | Solo `oauth2`: endpoint de autorización propio (nubes soberanas u otro proveedor OIDC). |
| `auth.entra.token_url` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__TOKEN_URL` | Solo `oauth2`: endpoint de token propio. |
| `auth.entra.issuer` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__ISSUER` | Solo `oauth2`: valor esperado del claim `iss`. |
| `auth.entra.logout_url` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__LOGOUT_URL` | Endpoint de cierre de sesión propio. |
| `auth.entra.timeout_seconds` | entero | `15` | Sí | `STORAGEWEB_AUTH__ENTRA__TIMEOUT_SECONDS` | Tiempo máximo de espera al endpoint de token, en segundos. |
| `auth.entra.secret_expires` | texto | `""` | Sí | `STORAGEWEB_AUTH__ENTRA__SECRET_EXPIRES` | Fecha de caducidad del `client_secret` (ISO 8601). La rellenan el registro automático y la renovación; con ella se avisa a los admins `secret_warn_days` días antes. |
| `auth.entra.secret_months` | entero | `24` | Sí | `STORAGEWEB_AUTH__ENTRA__SECRET_MONTHS` | Meses que vale un `client_secret` que crea StorageWeb (registrar la aplicación, *Renovar el secreto*, *Reparar*), de 1 a 24. Microsoft admite hasta 24; si las directivas del tenant piden menos (p. ej. 6 o 12), pon ese número o Entra ID rechazará el secreto. |
| `auth.entra.secret_warn_days` | entero | `30` | Sí | `STORAGEWEB_AUTH__ENTRA__SECRET_WARN_DAYS` | Días antes de que caduque el `client_secret` en que empieza el aviso del Resumen (de 1 a 365). |

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
| `security.api_token_unused_days` | entero | `90` | Sí | `STORAGEWEB_SECURITY__API_TOKEN_UNUSED_DAYS` | Días sin usarse tras los que el Resumen avisa de los tokens de API que siguen valiendo (mejor revocarlos: si uno se filtra, sigue funcionando). `0` = sin aviso; de 0 a 3650. |
| `security.webdav` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__WEBDAV` | Unidad de red: servidor WebDAV en `/dav/` (Windows, macOS, Linux, rclone…). Se entra con el nombre de usuario y un token de API como contraseña. Necesita `api_tokens` salvo que se admita la contraseña de la cuenta. |
| `security.webdav_passwords` | booleano | `false` | Sí | `STORAGEWEB_SECURITY__WEBDAV_PASSWORDS` | Admitir también la contraseña de la cuenta (usuarios locales y PAM) en WebDAV. Desactivado: solo tokens, que se pueden revocar y limitar a lectura. |
| `security.mfa_required` | texto | `"off"` | Sí | `STORAGEWEB_SECURITY__MFA_REQUIRED` | Quién debe tener la **verificación en dos pasos** (TOTP): `off` (nadie, quien quiera la activa en *Mi perfil*), `admins` (los administradores) o `all` (todas las cuentas). Solo las cuentas con contraseña (locales y PAM): quien entra con Microsoft Entra ID usa el segundo factor de Microsoft. Quien la debe y no la tiene la configura al iniciar sesión; quien la tiene la usa siempre, diga lo que diga esto. |
| `security.passkeys` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__PASSKEYS` | Permitir **passkeys** (WebAuthn: Windows Hello, Touch ID, el móvil o una llave de seguridad) como segundo paso, además de la app de códigos; cada cuenta puede tener varias. Necesitan que `network.public_url` tenga un nombre (no una IP) y HTTPS, salvo `localhost`: la passkey queda atada a ese nombre y no se puede mover a otro. Desactivado, no se ofrecen ni se aceptan (las cuentas que solo tengan passkeys entran con sus códigos de recuperación). |
| `security.passkey_login` | booleano | `false` | Sí | `STORAGEWEB_SECURITY__PASSKEY_LOGIN` | **Entrar solo con una passkey**, sin escribir el usuario ni la contraseña: un botón *Entrar con una passkey* en la página de inicio de sesión. La passkey tiene que verificar a la persona (PIN, huella o cara), así que vale por los dos pasos. Solo para las cuentas que guardan aquí su contraseña (las locales): en las de PAM decide el sistema si la cuenta sigue valiendo, y eso solo se sabe con su contraseña. Necesita `security.passkeys`. Las passkeys añadidas con esto encendido se guardan en el dispositivo (*credencial residente*), que es lo que permite elegirlas sin escribir el usuario. |
| `security.password_check` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__PASSWORD_CHECK` | Al poner una contraseña (crear una cuenta, cambiarla en *Mi perfil* o un administrador a otra persona), rechazar las **más comunes**: la lista de unas 19 000 que viaja con StorageWeb o, si se ha descargado o subido una en *Seguridad → Contraseñas* (o con `storageweb-admin password-list`), la propia del servidor (`<data_dir>/common_passwords.txt`). No se consulta nada fuera. Las contraseñas que ya existen no se tocan. |
| `security.password_min_length` | entero | `10` | Sí | `STORAGEWEB_SECURITY__PASSWORD_MIN_LENGTH` | Longitud mínima de una contraseña nueva de las cuentas locales, de `10` (nunca menos) a `128`. Se aplica al ponerla (alta, *Mi perfil*, un administrador o la CLI); las que ya existen no se tocan. |
| `security.password_min_distinct` | entero | `4` | Sí | `STORAGEWEB_SECURITY__PASSWORD_MIN_DISTINCT` | Caracteres distintos que tiene que tener como mínimo una contraseña nueva, de `1` (sin comprobar) a `20`: `aaaaaaaaaa` o `abababababab` son largas, pero se adivinan enseguida. |
| `security.password_require` | lista | `[]` | Sí | `STORAGEWEB_SECURITY__PASSWORD_REQUIRE` | Tipos de caracteres que tiene que tener una contraseña nueva: `lower` (minúscula), `upper` (mayúscula), `digit` (número) y `symbol` (cualquier otro). De serie, ninguno: la longitud protege más y obligar a mezclar las hace difíciles de recordar más que de adivinar (NIST SP 800-63B). |
| `security.password_reject_username` | booleano | `true` | Sí | `STORAGEWEB_SECURITY__PASSWORD_REJECT_USERNAME` | Rechazar las contraseñas que contienen el nombre de usuario (sin distinguir mayúsculas). |
| `security.password_blocklist` | lista | `[]` | Sí | `STORAGEWEB_SECURITY__PASSWORD_BLOCKLIST` | Palabras propias que una contraseña nueva no puede **contener**, sin distinguir mayúsculas: el nombre de la empresa, del servicio, la ciudad… De 4 caracteres o más. Se aplica aunque las comunes estén apagadas. |
| `security.password_breach_check` | booleano | `false` | Sí | `STORAGEWEB_SECURITY__PASSWORD_BREACH_CHECK` | Rechazar las contraseñas que aparecen en **filtraciones conocidas**, preguntando a Pwned Passwords de Have I Been Pwned (`api.pwnedpasswords.com`) al ponerlas. Solo se envían los 5 primeros caracteres de su SHA-1 (k-anonimato): ni la contraseña ni su hash completo salen del servidor. **Sale a internet**; si el servicio no contesta, la contraseña se acepta. |
| `security.password_list_urls` | lista | `["https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/Pwdb_top-1000000.txt", "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/Language-Specific/Spanish_Pwdb_common-password-list-top-150.txt"]` | Sí | `STORAGEWEB_SECURITY__PASSWORD_LIST_URLS` | De dónde se descarga la lista propia de contraseñas comunes (*Descargar ahora* en *Seguridad → Contraseñas* o `storageweb-admin password-list --download`): direcciones `https://` de ficheros de texto con una por línea, que se juntan. De serie, las de SecLists de las que sale la lista de serie, en su versión actual. Solo se guardan las de 10 caracteres o más, en minúsculas, con un tope de 64 MB. |
| `security.dependency_check_hours` | entero | `24` | Sí | `STORAGEWEB_SECURITY__DEPENDENCY_CHECK_HOURS` | Cada cuántas horas se comprueban solas las bibliotecas instaladas (Python y el JavaScript copiado) contra OSV.dev (vulnerabilidades conocidas) y PyPI y npm (versiones nuevas), de `0` a `720`; de serie `24` (una vez al día); `0` = solo con el botón *Comprobar ahora*. **Sale a internet** (`pypi.org`, `registry.npmjs.org`, `api.osv.dev`): en un servidor sin salida, ponlo a `0`. El resultado se ve en *Seguridad → Vulnerabilidades* y, si las hay, en el Resumen y en *Estado de la seguridad*.  |

## preview

| Clave | Tipo | Por defecto | Web | Variable | Descripción |
|---|---|---|---|---|---|
| `preview.enabled` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__ENABLED` | Abrir en el navegador, sin descargarlos, los archivos de texto y Markdown, las imágenes, los PDF, los vídeos y el audio (doble clic en el explorador; cada tipo multimedia se puede apagar aparte). Desactivado, todos se descargan como cualquier otro archivo. |
| `preview.diagrams` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__DIAGRAMS` | Dibujar los diagramas `mermaid` de los `.md` (con Mermaid, en un marco aislado del resto de la página). Desactivado, se ve su código y Mermaid no se descarga. |
| `preview.highlight` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__HIGHLIGHT` | Colorear el código (Python, PHP, JavaScript, SQL, YAML, PowerShell… y los bloques de código de los `.md`) con highlight.js. Desactivado, se ve sin colores y highlight.js no se descarga. Los archivos de más de 1 MB se ven siempre sin colores. |
| `preview.images` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__IMAGES` | Ver las imágenes en el visor: `png`, `jpg`, `gif`, `webp`, `bmp`, `ico` y `avif`. El SVG no: puede llevar código, así que se ve como texto (si `svg` está en las extensiones). Desactivado, se descargan. |
| `preview.pdf` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__PDF` | Ver los PDF en el visor, con el visor de PDF del propio navegador (aislado de la página). Desactivado, o en un navegador sin visor de PDF, se descargan. |
| `preview.video` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__VIDEO` | Reproducir los vídeos en el visor: `mp4`, `m4v`, `webm` y `ogv`, con lo que sepa reproducir el navegador; se piden por partes, así que se puede saltar a cualquier punto. Desactivado, se descargan. |
| `preview.audio` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__AUDIO` | Reproducir el audio en el visor: `mp3`, `wav`, `ogg`, `oga`, `opus`, `m4a`, `aac`, `flac` y `weba`. Desactivado, se descargan. |
| `preview.thumbnails` | booleano | `true` | Sí | `STORAGEWEB_PREVIEW__THUMBNAILS` | Miniaturas de las imágenes en el explorador (en la lista y, más grande, en el panel de detalle). Las genera el servidor con **Pillow**, que es opcional (`pip install storageweb[thumbnails]`; sin él se ven iconos), y las guarda en `<data_dir>/thumbnails`, nunca en la carpeta de nadie. Solo de las imágenes que abre el visor (`preview.images`), con el decodificador de su formato y nada más. Ver una miniatura no cuenta en la auditoría. |
| `preview.thumbnail_max_mb` | entero | `30` | Sí | `STORAGEWEB_PREVIEW__THUMBNAIL_MAX_MB` | La imagen más grande de la que se hace miniatura, en MB (de `1` a `500`): el servidor la lee entera para reducirla. Más grande, se ve el icono. |
| `preview.thumbnail_cache_mb` | entero | `500` | Sí | `STORAGEWEB_PREVIEW__THUMBNAIL_CACHE_MB` | Lo que pueden ocupar las miniaturas guardadas, en MB (de `10` a `100000`). Una vez al día se borran las que nadie ha pedido en 60 días y, si aun así ocupan más, las menos usadas. Cada una ocupa unos 10 KB. |
| `preview.max_mb` | entero | `2` | Sí | `STORAGEWEB_PREVIEW__MAX_MB` | Tamaño máximo, en MB, de un archivo de texto para verse en el navegador (de 1 a 20); más grande, se descarga (un log, por trozos). No se aplica a imágenes, PDF, vídeo ni audio. |
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
| `audit.file` | texto | `""` | Sí | `STORAGEWEB_AUDIT__FILE` | Escribir también cada evento en este fichero, uno en JSON por línea, para que lo lea un agente (Filebeat, Fluent Bit, Wazuh…); vacío = no. Se abre en cada escritura, así que se puede rotar con logrotate. Como el servidor añade líneas a ese fichero: fuera de la carpeta de datos (y nunca el config.json), dentro de `storage.allowed_folders` si las hay, y una ruta de red solo si está en ellas. |

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
| `timeout` | segundos (1-600) | `30` |  | Segundos que se espera al servidor (conectar y cada respuesta) antes de dar la operación por fallida (de 1 a 600). Súbelo para un servidor lento o lejano. |
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
| `timeout` | segundos (1-600) | `20` |  | Segundos que se espera al servidor (conectar y cada respuesta) antes de dar la operación por fallida (de 1 a 600). Súbelo para un servidor lento o lejano. |
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
| `timeout` | segundos (1-600) | `30` |  | Segundos que se espera al servidor (conectar y cada respuesta) antes de dar la operación por fallida (de 1 a 600). Súbelo para un servidor lento o lejano. |
| `username` | texto |  |  | Usuario. |
| `password` | texto (secreto) |  |  | Contraseña o contraseña de aplicación (secreto). |

## Ejemplo

El fichero `config/config.example.json` del repositorio (instalado en `/etc/storageweb/config.json` por los paquetes) solo trae lo de arranque y la plantilla de las carpetas personales: así lo demás se puede cambiar desde la web.

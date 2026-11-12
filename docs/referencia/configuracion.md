<!-- Generado por tools/gen_docs.py: no editar a mano -->

# Referencia de configuración

Todas las opciones de `config.json`, con su valor por defecto. Las rutas relativas se resuelven respecto a la carpeta donde está el `config.json`.

- **Web**: «Sí» = se puede cambiar en *Administración → Ajustes* (se aplica al momento y tiene prioridad sobre `config.json`). «No» = solo en `config.json` y requiere reiniciar el servicio.
- Los valores secretos nunca se muestran en la web.

## General

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `app_name` | texto | `"StorageWeb"` | Sí | Nombre que se muestra en la cabecera y en el título de las páginas. |
| `secret_key` | texto | `""` | No | Clave para firmar las cookies de sesión. Vacía = se genera y guarda en `<data_dir>/secret_key`. |
| `data_dir` | texto | `"data"` | No | Carpeta de datos del servicio (base de datos, `secret_key`, copias de seguridad). |
| `database` | texto | `""` | No | Ruta del fichero SQLite. Vacía = `<data_dir>/storageweb.db`. |

## default_locale

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `default_locale` | texto | `"en"` | Sí | Idioma por defecto de la interfaz (`en` o `es`) cuando el usuario no ha elegido uno y el navegador no indica ninguno disponible. |

## Servidor (`server`)

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `server.host` | texto | `"127.0.0.1"` | No | Dirección en la que escucha el servidor. Con un proxy inverso delante, `127.0.0.1`. |
| `server.port` | entero | `8080` | No | Puerto TCP de escucha. |
| `server.threads` | entero | `8` | No | Hilos de Waitress para atender peticiones en paralelo. |
| `server.behind_proxy` | booleano | `true` | No | Confiar en las cabeceras `X-Forwarded-*` (IP real, HTTPS, host) de un proxy inverso. Actívalo solo si hay un proxy delante. |
| `server.max_upload_mb` | entero | `2048` | No | Tamaño máximo de cada petición HTTP: cada parte de una subida y la subida clásica sin JavaScript. No limita el tamaño de los archivos (ver `storage.max_file_size_mb`). |

## Sesión (`session`)

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `session.lifetime_hours` | entero | `8` | No | Duración de la sesión iniciada, en horas. |
| `session.cookie_secure` | booleano | `true` | No | Enviar la cookie de sesión solo por HTTPS. Debe ser `true` en producción; `false` solo para pruebas en `http://localhost`. |

## Almacenamiento (`storage`)

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `storage.home_template` | texto | `"data/homes/{username}"` | Sí | Ruta de la carpeta personal. Debe contener `{username}`, que se sustituye por el nombre de usuario saneado. |
| `storage.create_home` | booleano | `true` | Sí | Crear la carpeta personal en el primer acceso del usuario. |
| `storage.create_shares` | booleano | `false` | Sí | Crear las carpetas compartidas si no existen (útil en desarrollo y Docker). |
| `storage.show_hidden` | booleano | `false` | Sí | Mostrar archivos y carpetas que empiezan por punto. |
| `storage.max_file_size_mb` | entero | `0` | Sí | Tamaño máximo por archivo en MB; `0` = sin límite. |
| `storage.shares` | lista | `[]` | Sí | Lista de carpetas compartidas (ver los campos de cada elemento abajo). |
| `storage.shares[].name` | | | Sí | Identificador en la URL (`/f/<name>/`): letras, números, `_` y `-`. `home` está reservado. |
| `storage.shares[].label` | | | Sí | Nombre visible. Por defecto, `name`. |
| `storage.shares[].path` | | | Sí | Ruta en el servidor. Relativa = respecto a la carpeta del `config.json`. |
| `storage.shares[].read_only` | | | Sí | Solo lectura: únicamente se permite descargar, también a los administradores. |
| `storage.shares[].users` | | | Sí | Usuarios con acceso; `["*"]` = todos. |
| `storage.shares[].groups` | | | Sí | Grupos con acceso (locales, del sistema, o Object IDs/App Roles de Entra ID). |

## Permisos (`permissions`)

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `permissions.user.upload` | booleano | `true` | Sí | El rol `user` puede subir archivos. |
| `permissions.user.download` | booleano | `true` | Sí | El rol `user` puede descargar archivos. |
| `permissions.user.mkdir` | booleano | `true` | Sí | El rol `user` puede crear carpetas. |
| `permissions.user.rename` | booleano | `false` | Sí | El rol `user` puede renombrar archivos y carpetas. |
| `permissions.user.delete` | booleano | `false` | Sí | El rol `user` puede eliminar archivos y carpetas. |

## Autenticación (`auth`)

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `auth.local.enabled` | booleano | `true` | Sí | Permitir el inicio de sesión de usuarios locales (guardados en SQLite). |
| `auth.pam.enabled` | booleano | `false` | Sí | Permitir el inicio de sesión de usuarios del sistema operativo mediante PAM (Linux/macOS). |
| `auth.pam.service` | texto | `"login"` | Sí | Servicio PAM que se usa para autenticar. |
| `auth.pam.allowed_groups` | lista | `[]` | Sí | Si no está vacío, solo entran los miembros de estos grupos del sistema. |
| `auth.pam.admin_groups` | lista | `[]` | Sí | Los miembros de estos grupos del sistema reciben el rol `admin`. |
| `auth.pam.use_system_home` | booleano | `false` | Sí | Usar el home real del usuario (`/home/<usuario>`) en vez de `storage.home_template`. |
| `auth.entra.enabled` | booleano | `false` | Sí | Activar el inicio de sesión con Microsoft Entra ID. |
| `auth.entra.provider` | texto | `"oauth2"` | Sí | Implementación: `oauth2` (propia, sin descubrimiento por red) o `msal` (librería de Microsoft). |
| `auth.entra.tenant_id` | texto | `""` | Sí | Directory (tenant) ID. También admite `organizations` o `common` (multi-tenant). |
| `auth.entra.client_id` | texto | `""` | Sí | Application (client) ID del registro de aplicación. |
| `auth.entra.client_secret` | texto | `""` | Sí | Secreto del registro de aplicación. Nunca se muestra en la web. |
| `auth.entra.redirect_uri` | texto | `""` | Sí | URL de vuelta registrada en Entra ID, p. ej. `https://files.midominio.com/auth/entra/callback`. Vacía = se calcula a partir de la petición. |
| `auth.entra.scopes` | lista | `["User.Read"]` | Sí | Scopes adicionales a `openid profile email`. |
| `auth.entra.button_label` | texto | `""` | Sí | Texto del botón de inicio de sesión. Vacío = texto por defecto en el idioma del usuario. |
| `auth.entra.username_claim` | texto | `"preferred_username"` | Sí | Claim del id_token que se usa como nombre de usuario. |
| `auth.entra.strip_domain` | booleano | `false` | Sí | Quitar el dominio del nombre de usuario (`juan@contoso.com` → `juan`). Cuidado con las colisiones con usuarios locales. |
| `auth.entra.allowed_groups` | lista | `[]` | Sí | Grupos (Object ID) o App Roles permitidos; vacío = cualquier usuario del tenant. |
| `auth.entra.auto_provision` | booleano | `true` | Sí | Crear el usuario automáticamente en su primer inicio de sesión. Si es `false`, solo entran los usuarios dados de alta antes por un administrador. |
| `auth.entra.default_role` | texto | `"user"` | Sí | Rol de los usuarios nuevos cuando no aplica ningún mapeo (`user` o `admin`). |
| `auth.entra.role_mappings` | objeto | `{}` | Sí | Grupo (Object ID) o App Role → rol, p. ej. `{"StorageWeb.Admin": "admin"}`. Si coinciden varios, gana `admin`. |
| `auth.entra.sync_role_on_login` | booleano | `true` | Sí | Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión. |
| `auth.entra.single_logout` | booleano | `false` | Sí | Cerrar también la sesión de Microsoft al salir. |
| `auth.entra.authorize_url` | texto | `""` | Sí | Solo `oauth2`: endpoint de autorización propio (nubes soberanas u otro proveedor OIDC). |
| `auth.entra.token_url` | texto | `""` | Sí | Solo `oauth2`: endpoint de token propio. |
| `auth.entra.issuer` | texto | `""` | Sí | Solo `oauth2`: valor esperado del claim `iss`. |
| `auth.entra.logout_url` | texto | `""` | Sí | Endpoint de cierre de sesión propio. |
| `auth.entra.timeout_seconds` | entero | `15` | Sí | Tiempo máximo de espera al endpoint de token, en segundos. |

## Seguridad (`security`)

| Clave | Tipo | Por defecto | Web | Descripción |
|---|---|---|---|---|
| `security.max_login_failures` | entero | `5` | Sí | Intentos fallidos (por IP o por usuario) antes de bloquear temporalmente el login. |
| `security.lockout_minutes` | entero | `15` | Sí | Duración del bloqueo tras demasiados intentos fallidos, en minutos. |

## Ejemplo

El fichero `config/config.example.json` del repositorio (instalado en `/etc/storageweb/config.json` por los paquetes) es un punto de partida completo.

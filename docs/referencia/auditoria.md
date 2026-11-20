# Registro de auditoría

Cada acción relevante se guarda en la tabla `audit_log`. Se puede consultar en *Seguridad → Auditoría*, filtrando por usuario y acción, o con `storageweb-admin audit`.

![Seguridad → Auditoría](../img/admin/auditoria.webp)

| Campo | Contenido |
|---|---|
| `ts` | Fecha y hora en UTC (ISO 8601) |
| `username` | Usuario que hace la acción (`cli` para comandos de administración) |
| `action` | Tipo de evento (tabla siguiente) |
| `target` | Objeto afectado: `raíz:/ruta` en archivos, nombre de usuario o fichero de copia |
| `ip` | IP del cliente (real si `server.behind_proxy` está activo detrás de un proxy) |
| `detail` | Información adicional |

## Acciones

| Acción | Cuándo | `detail` |
|---|---|---|
| `login` | Inicio de sesión correcto | Origen: `local`, `pam` o `entra`; con verificación en dos pasos, `+totp` (código de la aplicación) o `+recovery` (código de recuperación): `local+totp` |
| `login_failed` | Contraseña incorrecta, error del proveedor SSO o credenciales de la unidad de red no válidas | `entra:<código>` en SSO; en WebDAV, `webdav:bad_token`, `webdav:bad_password`, `webdav:password_not_allowed` (se usó la contraseña de la cuenta sin estar admitida) o `webdav:mfa_requires_token` (contraseña correcta de una cuenta con verificación en dos pasos: en la unidad de red solo valen tokens) |
| `login_blocked` | Intento durante un bloqueo por intentos fallidos | `mfa` si fue al escribir el código del segundo paso |
| `mfa_enrolled` | Verificación en dos pasos activada | `self` (desde *Mi perfil*) o `forced` (la política la exigía y se configuró al iniciar sesión) |
| `mfa_failed` | Código del segundo paso rechazado (cuenta como intento fallido) | `stage=verify` (al entrar), `enrol` (al activarla) o `manage` (al cambiarla en *Mi perfil*), y `error=empty` o `bad_code` |
| `mfa_recovery_used` | Se gastó un código de recuperación | `left=<los que quedan>` |
| `mfa_recovery_regenerated` | Juego nuevo de códigos de recuperación (los anteriores dejan de valer) | |
| `mfa_disabled` | Verificación en dos pasos desactivada por su dueño | `self` |
| `mfa_reset_by_admin` | Un administrador (o `cli`, con `mfa-reset`) quitó la verificación en dos pasos de otra cuenta | |
| `login_denied` | Cuenta de Entra rechazada (tenant, grupo, conflicto, no dada de alta, desactivada) | `entra:<motivo>` |
| `logout` | Cierre de sesión | `entra:frontchannel` si la cerró Microsoft (cierre de sesión de canal frontal) |
| `user_provisioned` | Usuario de Entra creado automáticamente | `entra:<rol>` |
| `user_linked` | Usuario de Entra dado de alta antes, vinculado en su primer login | |
| `role_changed` | Rol recalculado en el login o en la revisión periódica a partir de `role_mappings` | `anterior->nuevo (entra)` o `(entra:directory)` |
| `user_renamed` | Cuenta de Entra renombrada al entrar porque cambió su UPN | `anterior -> nuevo`, y `home moved` (carpeta personal renombrada) o `home kept` (se conserva la antigua como ruta propia) |
| `user_rename_failed` | No se pudo renombrar: el nombre nuevo ya es de otra cuenta, o las carpetas compartidas que la nombran están fijadas en `config.json` | Motivo |
| `directory_synced` | Revisión periódica de las cuentas contra Entra ID que cambió algo | Recuento: revisadas, desactivadas, reactivadas, actualizadas, sin respuesta, grupos |
| `user_created` | Alta de usuario desde la web | `origen:rol` |
| `user_updated` | Edición de usuario desde la web | Rol, estado y cambio de contraseña |
| `user_deleted` | Baja de usuario desde la web | |
| `user_disabled` | Cuenta desactivada desde la web (botón *Desactivar*) o por la revisión contra Entra ID (*usuario* = `system`) | Origen de la cuenta, o `entra:deleted` / `entra:disabled` / `entra:not_allowed` y las sesiones cerradas |
| `user_enabled` | Cuenta activada de nuevo desde la web, o sola cuando Entra ID la vuelve a dejar entrar | Origen de la cuenta, o `entra:directory` / `entra:signin` |
| `group_created` | Alta de grupo | `origen:grupo externo` |
| `group_updated` | Edición de grupo | `origen:grupo externo` |
| `group_deleted` | Baja de grupo | |
| `group_member_added` | Usuario añadido a mano a un grupo (*target* = grupo) | Usuario |
| `group_member_removed` | Usuario quitado de un grupo (*target* = grupo) | Usuario |
| `group_access_updated` | Cambios guardados en la matriz de accesos | `grupo@carpeta=nivel, …` |
| `share_created` | Carpeta compartida creada en *Acceso → Carpetas compartidas* (*target* = carpeta) | Ruta |
| `share_updated` | Carpeta compartida guardada (nombre, ruta o quién entra) | `quién=nivel, …` |
| `share_deleted` | Carpeta compartida quitada (los archivos se quedan en el servidor) | Ruta |
| `location_created` | Ubicación de almacenamiento creada en *Sistema → Almacenamiento externo* (*target* = ubicación) | Dirección (`s3://…`, `\servidor
ecurso`) |
| `location_updated` | Ubicación de almacenamiento guardada | Dirección |
| `location_tested` | Prueba de conexión de una ubicación | `ok` o el error |
| `location_deleted` | Ubicación quitada (los archivos se quedan donde estaban) | Dirección |
| `profile_updated` | El usuario guarda su perfil | Campos guardados |
| `password_changed` | El usuario cambia su contraseña desde su perfil | |
| `password_change_failed` | Intento de cambio de contraseña con la contraseña actual incorrecta | |
| `settings_updated` | Ajustes web guardados | Sección (`general`, `auth`…) o paso del asistente de Entra ID |
| `entra_app_registered` | Aplicación creada en Entra ID con *Registrar en Entra ID* (*target* = Client ID) | Tenant |
| `entra_app_repaired` | *Reparar automáticamente* revisó la aplicación de Entra ID y arregló lo que faltaba | Lo arreglado (o `-` si nada) |
| `entra_app_register_failed` | Falló el registro automático en Entra ID | Motivo |
| `entra_secret_rotated` | Secreto de Entra ID renovado con *Renovar secreto* (*target* = Client ID) | Nueva caducidad |
| `entra_groups_granted` | Se concedió `Group.Read.All` a la aplicación (*target* = Client ID) |  |
| `session_closed` | Un admin o el propio usuario cerró una sesión | IP de la sesión |
| `sessions_closed` | Se cerraron varias sesiones: las de un usuario (web o `sessions-close`), todas (*target* `*`), las seleccionadas (`selected`) o las inactivas (`idle>Nh`) | Número de sesiones |
| `api_token_created` | El usuario creó un token de API (en *Mi perfil*, o una aplicación al canjear su autorización: detalle `connect`) | Nombre del token |
| `app_authorized` | El usuario permitió a una aplicación (la extensión de VS Code) conectarse a su cuenta desde el navegador; el token se crea al canjearlo (`api_token_created`) | Nombre del equipo |
| `api_token_rotated` | El usuario rotó un token de API (*Mi perfil*): uno nuevo con el mismo nombre, alcance y caducidad; el anterior deja de valer | Nombre del token |
| `api_token_revoked` | Token de API revocado por su usuario o por un admin | Nombre del token |
| `ip_banned` | IP bloqueada (automática por infracciones o manual) | `auto:<tipo>:<n>` o `manual:<motivo>` |
| `ip_unbanned` | IP desbloqueada (web o `ip-unban`) |  |
| `ip_allowed` | IP o red añadida a la lista blanca | Nota |
| `ip_allow_removed` | IP o red quitada de la lista blanca |  |
| `audit_purged` | Entradas de auditoría borradas por la retención | Número de entradas |
| `audit_exported` | Auditoría exportada a CSV | Número de filas |
| `db_vacuum` | Base de datos compactada | Tamaño antes→después (bytes) |
| `backup_created` | Copia de seguridad creada (web o automática) | `web` o `auto` |
| `backup_downloaded` | Copia de seguridad descargada desde la web |  |
| `backup_deleted` | Copia de seguridad borrada desde la web |  |
| `backup_uploaded` | Copia de seguridad subida desde la web (de este u otro servidor) | Tamaño en bytes |
| `backup_restored` | Copia restaurada desde la web (en la base de datos restaurada) | Versión del esquema, copia previa y sesiones cerradas |
| `secrets_key_rotated` | Clave de los secretos cambiada con `rotate-secrets-key` (*usuario* = `cli`) | Juegos de ajustes vueltos a cifrar |
| `backup_failed` | Falló una copia automática | Error |
| `branding_logo_updated` | Logo propio subido | Fichero |
| `branding_logo_removed` | Logo propio quitado |  |
| `branding_login_image_updated` | Imagen propia del inicio de sesión subida | Fichero |
| `branding_login_image_removed` | Imagen propia del inicio de sesión quitada (vuelve la de serie) |  |
| `settings_field_reset` | Un ajuste vuelve a su valor predeterminado (*Restablecer*) | Ruta del ajuste |
| `settings_reset` | Ajustes web descartados (web o `settings-reset`) | |
| `upload` | Archivo subido (también al copiar por la unidad de red) | Tamaño en bytes; por la unidad de red, `webdav:<bytes>` o `webdav:copy:<destino>` |
| `download` | Archivo descargado | Por la unidad de red, `webdav`; abierto en el visor, `view` |
| `mkdir` | Carpeta creada | Por la unidad de red, `webdav` |
| `rename` | Archivo o carpeta renombrado o movido | Nombre nuevo; por la unidad de red, `webdav:move:<destino>` |
| `delete` | Archivo o carpeta eliminado | Por la unidad de red, `webdav` |
| `backup` | Copia de seguridad creada | |
| `restore` | Copia restaurada | Fecha y versión de la copia |

**Con qué programa.** Si la acción con archivos se hizo con un token de API, su detalle termina en `token=<nombre del token>`. Es el caso de la unidad de red, la extensión de VS Code y los scripts. Así se distingue, por ejemplo, un guardado desde VS Code (`webdav:1532 token=Visual Studio Code (PORTATIL-ANA)`, el nombre que pone la extensión al conectarse) de uno desde el Explorador de Windows con otro token. Con la contraseña de la cuenta, o desde la web, no hay token y el detalle no lo lleva. Pon a cada token un nombre que diga dónde se usa.

Listar carpetas por la unidad de red (`PROPFIND`) no se registra: los clientes lo hacen continuamente. La primera sincronización de VS Code de cada sesión sube y borra un archivo de prueba `.storageweb-probe-…`.

La tabla crece indefinidamente. Si necesitas purgarla, hazlo con SQL sobre una copia, o con el servicio parado:

```sql
DELETE FROM audit_log WHERE ts < '2025-01-01';
VACUUM;
```

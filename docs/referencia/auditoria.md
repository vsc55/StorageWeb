# Registro de auditoría

Cada acción relevante se guarda en la tabla `audit_log`. Se puede consultar en *Seguridad → Auditoría*, filtrando por usuario y acción, o con `storageweb-admin audit`.

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
| `login` | Inicio de sesión correcto | Origen: `local`, `pam` o `entra` |
| `login_failed` | Contraseña incorrecta o error del proveedor SSO | `entra:<código>` en SSO |
| `login_blocked` | Intento durante un bloqueo por intentos fallidos | |
| `login_denied` | Cuenta de Entra rechazada (tenant, grupo, conflicto, no dada de alta, desactivada) | `entra:<motivo>` |
| `logout` | Cierre de sesión | |
| `user_provisioned` | Usuario de Entra creado automáticamente | `entra:<rol>` |
| `user_linked` | Usuario de Entra dado de alta antes, vinculado en su primer login | |
| `role_changed` | Rol recalculado en el login a partir de `role_mappings` | `anterior->nuevo (entra)` |
| `user_created` | Alta de usuario desde la web | `origen:rol` |
| `user_updated` | Edición de usuario desde la web | Rol, estado y cambio de contraseña |
| `user_deleted` | Baja de usuario desde la web | |
| `user_disabled` | Cuenta desactivada desde la web (botón *Desactivar*) | Origen de la cuenta |
| `user_enabled` | Cuenta activada de nuevo desde la web | Origen de la cuenta |
| `group_created` | Alta de grupo | `origen:grupo externo` |
| `group_updated` | Edición de grupo | `origen:grupo externo` |
| `group_deleted` | Baja de grupo | |
| `group_member_added` | Usuario añadido a mano a un grupo (*target* = grupo) | Usuario |
| `group_member_removed` | Usuario quitado de un grupo (*target* = grupo) | Usuario |
| `group_access_updated` | Cambios guardados en la matriz de accesos | `grupo@carpeta=nivel, …` |
| `share_created` | Carpeta compartida creada en *Acceso → Carpetas compartidas* (*target* = carpeta) | Ruta |
| `share_updated` | Carpeta compartida guardada (nombre, ruta o quién entra) | `quién=nivel, …` |
| `share_deleted` | Carpeta compartida quitada (los archivos se quedan en el servidor) | Ruta |
| `location_created` | Ubicación de almacenamiento creada en *Sistema → Almacenamiento externo* (*target* = ubicación) | Dirección (`s3://…`, `\servidorecurso`) |
| `location_updated` | Ubicación de almacenamiento guardada | Dirección |
| `location_tested` | Prueba de conexión de una ubicación | `ok` o el error |
| `location_deleted` | Ubicación quitada (los archivos se quedan donde estaban) | Dirección |
| `profile_updated` | El usuario guarda su perfil | Campos guardados |
| `password_changed` | El usuario cambia su contraseña desde su perfil | |
| `password_change_failed` | Intento de cambio de contraseña con la contraseña actual incorrecta | |
| `settings_updated` | Ajustes web guardados | Sección (`general`, `auth`…) o paso del asistente de Entra ID |
| `entra_app_registered` | Aplicación creada en Entra ID con *Registrar en Entra ID* (*target* = Client ID) | Tenant |
| `entra_app_register_failed` | Falló el registro automático en Entra ID | Motivo |
| `entra_secret_rotated` | Secreto de Entra ID renovado con *Renovar secreto* (*target* = Client ID) | Nueva caducidad |
| `entra_groups_granted` | Se concedió `Group.Read.All` a la aplicación (*target* = Client ID) |  |
| `session_closed` | Un admin o el propio usuario cerró una sesión | IP de la sesión |
| `sessions_closed` | Se cerraron varias sesiones: las de un usuario (web o `sessions-close`), todas (*target* `*`), las seleccionadas (`selected`) o las inactivas (`idle>Nh`) | Número de sesiones |
| `api_token_created` | El usuario creó un token de API | Nombre del token |
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
| `backup_failed` | Falló una copia automática | Error |
| `branding_logo_updated` | Logo propio subido | Fichero |
| `branding_logo_removed` | Logo propio quitado |  |
| `settings_field_reset` | Un ajuste vuelve a su valor predeterminado (*Restablecer*) | Ruta del ajuste |
| `settings_reset` | Ajustes web descartados (web o `settings-reset`) | |
| `upload` | Archivo subido | Tamaño en bytes |
| `download` | Archivo descargado | |
| `mkdir` | Carpeta creada | |
| `rename` | Archivo o carpeta renombrado | Nombre nuevo |
| `delete` | Archivo o carpeta eliminado | |
| `backup` | Copia de seguridad creada | |
| `restore` | Copia restaurada | Fecha y versión de la copia |

La tabla crece indefinidamente. Si necesitas purgarla, hazlo con SQL sobre una copia, o con el servicio parado:

```sql
DELETE FROM audit_log WHERE ts < '2025-01-01';
VACUUM;
```

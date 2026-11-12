# Registro de auditoría

Cada acción relevante se guarda en la tabla `audit_log`. Se puede consultar en *Administración → Auditoría*, filtrando por usuario y acción, o con `storageweb-admin audit`.

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
| `profile_updated` | El usuario guarda su perfil | Campos guardados |
| `password_changed` | El usuario cambia su contraseña desde su perfil | |
| `password_change_failed` | Intento de cambio de contraseña con la contraseña actual incorrecta | |
| `settings_updated` | Ajustes web guardados | |
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

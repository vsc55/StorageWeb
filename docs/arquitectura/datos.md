# Datos

## Base de datos (SQLite)

Un único fichero (`storageweb.db`) en modo WAL. El esquema se crea y evoluciona con [migraciones versionadas](decisiones/0007-migraciones.md) en `src/storageweb/db/migrations/`.

```mermaid
erDiagram
    users {
        int id PK
        text username UK "NOCASE"
        text source "método de inicio de sesión: local | pam | entra…"
        text role "admin | user"
        text password_hash "solo local"
        text external_id "oid de Entra"
        text groups "lista efectiva (csv)"
        text external_groups "del proveedor (csv)"
        text home_path "opcional"
        text locale "es | en | NULL"
        text theme "system | light | dark | NULL"
        int enabled
        text created_at
        text last_login
    }
    groups {
        int id PK
        text name UK "lo usan las carpetas"
        text label
        text description
        text source "local o un método que trae grupos: entra | pam…"
        text external_id "Object ID, App Role o grupo del sistema"
        int builtin "1 = de serie (admins)"
        text created_at
    }
    user_groups {
        int user_id PK
        int group_id PK
        text origin "manual | sync"
        text added_at
    }
    users ||--o{ user_groups : ""
    groups ||--o{ user_groups : ""
    audit_log {
        int id PK
        text ts
        text username
        text action
        text target
        text ip
        text detail
        text level
    }
    settings_values {
        text profile PK "default"
        text path PK "auth.entra.client_secret"
        text value "JSON"
        int secret
        text updated_at
        text updated_by
    }
    settings_profiles {
        text name PK
        int revision
        text updated_at
        text updated_by
    }
    settings_profiles ||--o{ settings_values : ""
    shares {
        text profile PK
        text name PK
        text label
        text location
        text path
        int read_only
        int quota_mb
        int position
    }
    share_access {
        text profile PK
        text share PK
        text kind PK "all | user | group"
        text ref PK
        text level "read | write"
    }
    shares ||--o{ share_access : ""
    locations {
        text profile PK
        text name PK
        text label
        text type
        int position
    }
    location_options {
        text profile PK
        text location PK
        text name PK
        text value "JSON simple"
        int secret
    }
    locations ||--o{ location_options : ""
    settings {
        text key PK "maintenance_state"
        text value "JSON"
        int revision
        text updated_at
        text updated_by
    }
    mfa_factors {
        int user_id PK
        text method "totp"
        text secret "semilla cifrada (enc:v1:)"
        int confirmed "0 = alta a medias"
        int last_step "antirreplay"
    }
    mfa_recovery {
        int id PK
        int user_id
        text code_hash "nunca el código"
        text used_at
    }
    users ||--o| mfa_factors : ""
    users ||--o{ mfa_recovery : ""
    uploads {
        text id PK
        int user_id
        text root
        text dir_rel
        text dir_path
        text filename
        int size
        text created_at
        text updated_at
    }
```

| Tabla | Uso |
|---|---|
| `users` | Cuentas. `uid` es su identificador público (UUID v4): el que va en las direcciones y los formularios de la administración; `id` es la clave interna de las relaciones. `source` es la clave de su método de inicio de sesión (cualquiera registrado; sin `CHECK` desde la migración 007). `(source, external_id)` es único: una cuenta de Entra por `oid`. `username` no distingue mayúsculas. `groups` es la lista efectiva que usan las carpetas: `external_groups` más los nombres de sus grupos. |
| `groups` | Grupos dados de alta. Como los usuarios, `uid` es su identificador público. `(source, external_id)` es único. `home_quota_mb` es la cuota de la carpeta personal de sus miembros. `builtin = 1` marca el grupo de serie `admins` (migración 005), cuyos miembros son los usuarios con rol admin. Ver la [decisión 0011](decisiones/0011-grupos-gestionados.md). |
| `user_groups` | Pertenencias. Al iniciar sesión solo se reemplazan las `sync`; las `manual` se conservan. |
| `audit_log` | Registro de eventos, cada uno con su nivel (`level`: `debug`, `info`, `warning`, `error` o `critical`; migración 004); ver la [referencia de auditoría](../referencia/auditoria.md). |
| `settings_values` | Ajustes guardados desde la web: una fila por perfil (`settings_profile`) y campo, con su valor en JSON (los secretos, cifrados), y quién y cuándo lo cambió. Solo lo que difiere de los predeterminados. Ver la [decisión 0017](decisiones/0017-ajustes-web-por-campo.md). |
| `settings_profiles` | Un perfil por fila; `revision` sube en cada guardado para invalidar la caché de los ajustes efectivos. |
| `shares`, `share_access` | Carpetas compartidas creadas desde la web (por perfil) y quién entra en cada una: todos, un usuario o un grupo, con lectura o escritura. Las de `config.json` no están aquí: se leen del fichero y se ven de solo lectura. Ver la [decisión 0018](decisiones/0018-carpetas-y-ubicaciones-como-entidades.md). |
| `locations`, `location_options` | Ubicaciones de almacenamiento externo creadas desde la web y sus opciones (dependen del tipo); los secretos, cifrados. |
| `settings` | Estado interno como documentos JSON: cuándo corrió cada tarea de mantenimiento (`maintenance_state`), permisos del último inicio de sesión de cada método SSO… |
| `mfa_factors`, `mfa_recovery` | Verificación en dos pasos (migración 002): la semilla TOTP de cada cuenta, **cifrada** con la clave de los secretos (se vuelve a cifrar al rotarla o al restaurar una copia de otro servidor), si el alta está confirmada y el último paso aceptado (un código no vale dos veces); y el hash de sus códigos de recuperación, de un solo uso (de la cuenta: sirven con cualquier factor). |
| `mfa_passkeys` | Passkeys de cada cuenta (migración 005): id de la credencial (único), clave pública COSE tal como llegó, algoritmo fijado al registrar, último contador de firmas, nombre, AAGUID, alta y último uso. |
| `favorites` | Favoritos del explorador (migración 003): carpeta de StorageWeb (`home` es la personal de cada usuario) y ruta, por usuario. Se actualizan al renombrar, mover o borrar desde StorageWeb (web o unidad de red). *Recientes* no tiene tabla: sale de `audit_log` (índice por usuario y fecha). |
| `uploads` | Subidas por partes en curso. El progreso **no** se guarda aquí: es el tamaño del `.part`. |

`PRAGMA user_version` guarda la versión del esquema.

Cada sesión es una fila de `sessions` (navegador, IP, última actividad) y la cookie, firmada con `secret_key`, solo lleva su id, el del usuario y el token CSRF: cerrar una sesión es borrar su fila. Si cambias `secret_key`, las cookies dejan de valer y se cierran todas. Un inicio de sesión que espera el código del segundo paso **no** es una sesión: solo una nota en la cookie que caduca a los 5 minutos.

## Sistema de ficheros

```
<home_template>/<usuario>/       carpeta personal (se crea en el primer acceso)
<share.path>/                    cada carpeta compartida
  .sw-upload-<id>.part           subida en curso (oculta en el listado)
```

- **Propietario:** todo se escribe con el usuario del servicio. Con `UMask=0007` y el bit setgid (`2770`) en las carpetas creadas por los paquetes, los ficheros quedan legibles por el grupo `storageweb`.
- **Nombres de carpeta:** el nombre de usuario se sanea para usarlo como carpeta (`safe_username_for_path`): minúsculas y solo `[a-z0-9._@-]`.
- **Escrituras atómicas:** las subidas se escriben en el `.part` y se renombran al terminar, así que un archivo a medias nunca aparece con su nombre final.

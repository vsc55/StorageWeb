# Datos

## Base de datos (SQLite)

Un único fichero (`storageweb.db`) en modo WAL. El esquema se crea y evoluciona con [migraciones versionadas](decisiones/0007-migraciones.md) en `src/storageweb/db/migrations/`.

```mermaid
erDiagram
    users {
        int id PK
        text username UK "NOCASE"
        text source "local | pam | entra"
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
        text source "local | entra | pam"
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
    }
    settings {
        text key PK "runtime"
        text value "JSON"
        int revision
        text updated_at
        text updated_by
    }
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
| `users` | Cuentas. `(source, external_id)` es único: una cuenta de Entra por `oid`. `username` no distingue mayúsculas. `groups` es la lista efectiva que usan las carpetas: `external_groups` más los nombres de sus grupos. |
| `groups` | Grupos dados de alta. `(source, external_id)` es único. `builtin = 1` marca el grupo de serie `admins` (migración 005), cuyos miembros son los usuarios con rol admin. Ver la [decisión 0011](decisiones/0011-grupos-gestionados.md). |
| `user_groups` | Pertenencias. Al iniciar sesión solo se reemplazan las `sync`; las `manual` se conservan. |
| `audit_log` | Registro de eventos; ver la [referencia de auditoría](../referencia/auditoria.md). |
| `settings` | Ajustes web como un documento JSON (`key = runtime`). `revision` se incrementa en cada cambio para invalidar cachés. |
| `uploads` | Subidas por partes en curso. El progreso **no** se guarda aquí: es el tamaño del `.part`. |

`PRAGMA user_version` guarda la versión del esquema.

Las sesiones **no** se guardan en la base de datos: son cookies firmadas con `secret_key` que contienen el id de usuario y el token CSRF. Por eso, si cambias `secret_key`, se cierran todas las sesiones.

## Sistema de ficheros

```
<home_template>/<usuario>/       carpeta personal (se crea en el primer acceso)
<share.path>/                    cada carpeta compartida
  .sw-upload-<id>.part           subida en curso (oculta en el listado)
```

- **Propietario:** todo se escribe con el usuario del servicio. Con `UMask=0007` y el bit setgid (`2770`) en las carpetas creadas por los paquetes, los ficheros quedan legibles por el grupo `storageweb`.
- **Nombres de carpeta:** el nombre de usuario se sanea para usarlo como carpeta (`safe_username_for_path`): minúsculas y solo `[a-z0-9._@-]`.
- **Escrituras atómicas:** las subidas se escriben en el `.part` y se renombran al terminar, así que un archivo a medias nunca aparece con su nombre final.

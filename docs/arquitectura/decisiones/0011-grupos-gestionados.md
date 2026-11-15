# 0011. Grupos gestionados en SQLite con pertenencias manuales y sincronizadas

- **Estado:** Aceptada
- **Fecha:** 2026-11-12

## Contexto

Hasta la versión 1.0 los grupos eran una lista de texto en `users.groups`. Tenía tres problemas:

- No había dónde ver qué grupos existen, quién está en cada uno ni a qué carpetas dan acceso.
- Los grupos de Entra ID son Object IDs: las carpetas compartidas se configuraban con identificadores ilegibles.
- En cada inicio de sesión por Entra ID o PAM la lista se **sobrescribía** con lo que decía el proveedor, así que un grupo puesto a mano a un usuario de SSO se perdía.

## Decisión

- Tabla `groups` con `name` (lo que usan las carpetas), `label`, `description`, `source` (`local`, `entra`, `pam`) y `external_id` (Object ID, App Role o grupo del sistema).
- Tabla `user_groups` con `origin` = `manual` o `sync`. Al iniciar sesión **solo** se reemplazan las pertenencias `sync` del origen del usuario; las manuales se conservan. Si una pertenencia es manual y además llega del proveedor, sigue siendo manual.
- `users.external_groups` guarda lo que da el proveedor; `users.groups` pasa a ser la lista **efectiva** (`external_groups` ∪ nombres de sus grupos). Así las carpetas que ya referenciaban Object IDs siguen funcionando y el control de acceso (`core.storage`) no necesita consultar la base de datos.
- Grupo de serie `admins` (`builtin = 1`), que no se edita ni se borra. Sus miembros **no** se guardan en `user_groups`: son los usuarios con rol `admin`, y añadir o quitar miembros cambia el rol. El control de acceso añade `admins` según el rol en cada petición, así grupo y rol nunca se contradicen.
- El acceso por grupo puede ser de solo lectura: `storage.shares[].read_only_groups`. Un usuario solo escribe si entra por usuario o por algún grupo que no sea de solo lectura.
- La administración ofrece tres vistas (lista + ficha, maestro-detalle y matriz grupos × carpetas) sobre las mismas acciones, para elegir la definitiva con el uso.

## Alternativas consideradas

- **Mantener el texto y solo añadir una pantalla:** no resuelve que el login de SSO borre los grupos manuales.
- **Guardar el permiso por grupo en una tabla de SQLite:** separaría la definición de las carpetas (que vive en los ajustes y en `config.json`) de sus permisos.
- **Consultar las pertenencias en cada petición en lugar de la lista efectiva:** más simple de mantener coherente, pero obliga a pasar la conexión al control de acceso y añade consultas en cada petición.

## Consecuencias

- Los grupos manuales de los usuarios de SSO ya no se pierden.
- Cada cambio de pertenencias recalcula `users.groups` (`core.groups.refresh_user`); el código que escriba pertenencias debe usar `core.groups`, no el repositorio directamente.
- Se mantienen dos vistas, lista y paneles; la matriz de accesos pasó a ser una página de *Acceso* ([0012](0012-administracion-por-zonas.md)).

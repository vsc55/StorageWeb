# 0017. Ajustes web por campo, una fila por perfil y campo

- **Estado:** Aceptada
- **Fecha:** 2026-11-15

## Contexto

Los ajustes guardados desde la web eran un documento JSON por perfil en la tabla `settings` (claves `runtime` y `runtime:<perfil>`), con la diferencia mínima con los valores predeterminados ([0013](0013-capas-de-configuracion.md)). Eso tenía tres problemas:

- **Guardados que se pisan.** Cada guardado reescribía el documento entero. Si dos admins guardaban páginas distintas a la vez, el último deshacía lo del otro sin que nadie se enterara.
- **Sin historia por campo.** Solo se sabía quién guardó el documento por última vez, no quién cambió cada ajuste ni cuándo.
- **Opaco.** Para ver o arreglar un ajuste a mano había que leer y reescribir un JSON grande; los secretos cifrados había que buscarlos dentro.

## Decisión

Tabla `settings_values (profile, path, value, secret, updated_at, updated_by)`, **una fila por perfil y campo**, y `settings_profiles (name, revision, …)` con la revisión que invalida la caché.

- **Qué es un campo:** lo mismo que en `fields.py` y en los bloqueos. Cada hoja del árbol de ajustes, salvo las listas (`storage.shares`, `storage.locations`) y los diccionarios de `LEAF_PATHS` (`role_mappings`, `group_quotas`), que son un único campo con su valor en JSON, igual que cuando se fijan en `config.json`. Se sigue guardando solo lo que difiere de los predeterminados.
- **Guardar** escribe solo las filas que cambian, en una transacción (`BEGIN IMMEDIATE`). Quien guarda pasa la vista de la que partió (`base`): se aplican solo los campos que él cambió sobre lo que haya guardado *ahora*, y se valida el conjunto. Cada fila conserva quién y cuándo la cambió.
- **Perfiles:** `settings_profile` sigue eligiendo el juego de ajustes de cada instancia; ahora es una columna, no un prefijo en la clave. *Sistema → Información* muestra el perfil activo, los demás de la base de datos y quién cambió cada campo.
- La tabla `settings` queda para el **estado interno** (tareas de mantenimiento, permisos del último inicio de sesión de Entra ID…).

## Alternativas consideradas

- **Seguir con el documento y bloquear con la revisión** (rechazar el guardado si cambió la revisión desde que se abrió la página): evita perder cambios, pero obliga a repetir el guardado aunque se tocaran cosas distintas, y sigue sin historia por campo.
- **Una fila por cada hoja, también dentro de las listas** (`storage.shares.0.path`): las listas se editan y se fijan enteras; partirlas complicaría el orden, los bloqueos y la validación sin ventaja real.
- **Tablas propias para las carpetas compartidas y las ubicaciones:** son entidades, no ajustes. Se hizo justo después: [0018](0018-carpetas-y-ubicaciones-como-entidades.md).

## Consecuencias

- Dos guardados de cosas distintas no se pisan; si tocan el mismo campo, gana el último (como antes).
- Cada campo sabe quién y cuándo lo cambió.
- Las listas que quedan (patrones ocultos, redes, *scopes*) son una fila cada una. Carpetas, ubicaciones y cuotas de grupo pasaron a sus tablas ([0018](0018-carpetas-y-ubicaciones-como-entidades.md)).
- Las pruebas y herramientas no escriben JSON a mano: usan `store.put_doc` / `store.read_doc`.

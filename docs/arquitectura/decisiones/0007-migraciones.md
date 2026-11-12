# 0007. Migraciones SQL versionadas con `PRAGMA user_version`

- **Estado:** Aceptada
- **Fecha:** 2026-11-12

## Contexto

Al principio el esquema se creaba con `CREATE TABLE IF NOT EXISTS` y los cambios se aplicaban con `ALTER TABLE` sueltos en el código. Así no se sabe en qué versión está una base de datos, y cada cambio nuevo complica el arranque.

## Decisión

- **Ficheros numerados:** `db/migrations/NNN_descripcion.sql`, consecutivos y que **nunca se modifican** una vez publicados.
- **Versión en la base de datos:** `PRAGMA user_version` guarda la última migración aplicada.
- **Aplicación:** `migrate()` aplica las pendientes en orden, cada una en una transacción (`BEGIN … PRAGMA user_version = N; COMMIT`). Se ejecuta al arrancar y con `storageweb init-db`.
- **Adopción:** la `001` usa `IF NOT EXISTS` para adoptar bases de datos creadas antes de este sistema.
- **Tests:** comprueban la numeración consecutiva, la idempotencia, el rollback de una migración fallida y la adopción.

## Alternativas consideradas

- **Alembic:** potente, pero pensado para SQLAlchemy, que no se usa aquí.
- **Seguir con `IF NOT EXISTS` y `ALTER` sueltos:** no escala y no deja constancia de la versión.

## Consecuencias

- Las actualizaciones aplican las migraciones solas, de forma atómica.
- No hay migraciones hacia atrás: volver a una versión anterior requiere restaurar una copia ([Copias de seguridad](../../administracion/copias-seguridad.md)). `restore` se niega a restaurar copias de un esquema más nuevo que el instalado.

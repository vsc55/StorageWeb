# 0005. Ajustes web en SQLite con prioridad sobre `config.json`

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Los administradores quieren cambiar la configuración desde la web: carpetas compartidas, permisos, Entra ID. Pero `config.json` pertenece a `root` (`0640`), porque contiene secretos, y el servicio no debe poder escribirlo. Además, algunas opciones (puerto, base de datos, `secret_key`) solo tienen sentido al arrancar.

## Decisión

- **Dos niveles:** `config.json`, solo lectura para el servicio, más un documento JSON de **ajustes web** en la tabla `settings`, limitado a `app_name`, `storage`, `permissions`, `auth` y `security`.
- **Prioridad:** los ajustes web ganan sobre `config.json`, sección por sección.
- **Arranque solo en el fichero:** `server`, `data_dir`, `database`, `secret_key` y `session` solo se configuran en `config.json`.
- **Validación:** se hace con el mismo `normalize()` que `config.json`. Un ajuste no válido no se guarda.
- **Aplicación inmediata:** `settings.revision` se incrementa en cada cambio y cada petición compara la revisión para recalcular la configuración, sin reiniciar.
- **Vuelta atrás:** *Restablecer a config.json* en la web y `storageweb settings-reset` en la CLI, como vía de rescate.
- **Secretos:** un secreto vacío en el formulario conserva el anterior y nunca se muestra.

## Alternativas consideradas

- **Escribir `config.json` desde el servicio:** obliga a darle permisos de escritura sobre un fichero con secretos, y choca con la gestión por Ansible o Puppet.
- **Todo en la base de datos:** el arranque necesita configuración antes de poder abrir la base de datos.

## Consecuencias

- Administración cómoda sin acceso al servidor.
- Dos fuentes de verdad: la página de ajustes muestra la configuración efectiva y la fecha y el autor del último cambio para evitar confusiones.
- El `client_secret` puede acabar guardado en SQLite, que está en `0640` y en las copias en `0600`.

# 0006. Subidas por partes reanudables

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Una subida multipart en una sola petición tiene varios problemas:

- queda limitada por el tamaño máximo de petición (`client_max_body_size` de nginx, Waitress, Flask);
- ocupa la conexión durante toda la transferencia;
- si se corta, se pierde entera.

Los usuarios necesitan subir archivos de varios GB.

## Decisión

- **API JSON propia** (`/api/uploads`): el navegador trocea el archivo en partes de hasta 32 MB y las envía en orden con `PUT ?offset=N`.
- **Progreso en disco:** el estado real es el tamaño del fichero `.sw-upload-<id>.part`. Un `offset` incorrecto devuelve 409 con el valor correcto, así que el cliente se resincroniza solo.
- **Al terminar:** `complete` renombra de forma atómica al nombre final, sin sobrescribir.
- **Comprobaciones:** permisos en cada parte, espacio libre al empezar, tamaño máximo por archivo configurable y limpieza de subidas abandonadas a las 24 h.
- **Alternativa sin JavaScript:** se mantiene la subida multipart clásica, limitada por `server.max_upload_mb`.

## Alternativas consideradas

- **Protocolo tus:** estándar y con buenos clientes, pero añade una dependencia y su complejidad (extensiones, metadatos) no aporta para un solo cliente propio.
- **Subida directa a almacenamiento de objetos (S3):** fuera del alcance; aquí el almacenamiento es local.

## Consecuencias

- Sin límite práctico de tamaño, y reanudable tras cortes o recargas de la página.
- Más código, en el cliente (`files/upload.js`) y en el servidor (`core/uploads.py`), cubierto por tests unitarios y de integración.
- Los ficheros `.part` ocupan espacio hasta que se completan o se limpian.

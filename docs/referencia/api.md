<!-- Generado por tools/gen_docs.py: no editar a mano -->

# Referencia de la API

API JSON de StorageWeb. La usa la propia interfaz web para las subidas por partes.

**Autenticación:** cookie de sesión (`storageweb_session`) obtenida al iniciar sesión en la web.
Las peticiones que modifican datos (POST, PUT, DELETE) requieren además la cabecera
`X-CSRF-Token` con el valor de `<meta name="csrf-token">` de cualquier página.

**Errores:** siempre JSON, con la forma `{"error": "mensaje"}` (y campos extra en algunos casos).

La especificación completa está en [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1).

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/healthz` | Estado del servicio |
| `POST` | `/api/uploads` | Iniciar una subida |
| `GET` | `/api/uploads/{upload_id}` | Estado de una subida |
| `PUT` | `/api/uploads/{upload_id}` | Enviar una parte |
| `DELETE` | `/api/uploads/{upload_id}` | Cancelar una subida |
| `POST` | `/api/uploads/{upload_id}/complete` | Finalizar una subida |

## `GET /healthz`

**Estado del servicio.** Sin autenticación. Comprueba que la base de datos responde. Lo usa el healthcheck de Docker.

Autenticación: ninguna

| Respuesta | Descripción |
|---|---|
| `200` | Servicio operativo — `status`, `version` |
| `503` | La base de datos no responde — `status`, `detail` |

## `POST /api/uploads`

**Iniciar una subida.** Valida el permiso de subida, el nombre, el tamaño máximo por archivo y el espacio libre, y crea
un fichero temporal vacío. También elimina las subidas sin actividad desde hace más de 24 h.

Autenticación: `csrf`, `session`

Cuerpo (`application/json`):

| Campo | Tipo | Descripción |
|---|---|---|
| `root` * | string | `home` o el nombre de una carpeta compartida |
| `path` | string | Subcarpeta relativa dentro de `root` (vacío = raíz) |
| `name` * | string | Nombre del archivo |
| `size` * | integer | Tamaño total en bytes |

| Respuesta | Descripción |
|---|---|
| `201` | Subida creada — `id`, `name`, `size`, `received`, `chunk_size` |
| `400` | Petición no válida (token CSRF, nombre, tamaño u offset) — `error` |
| `401` | Sesión no iniciada — `error` |
| `403` | Sin permiso de subida en esa carpeta (rol o carpeta de solo lectura) — `error` |
| `404` | La subida o la carpeta no existe, o pertenece a otro usuario — `error` |
| `413` | El archivo supera `storage.max_file_size_mb` — `error` |
| `507` | No hay espacio suficiente en el servidor — `error` |

## `GET /api/uploads/{upload_id}`

**Estado de una subida.** Permite reanudar una subida interrumpida desde `received`.

Autenticación: `session`

| Parámetro | En | Descripción |
|---|---|---|
| `upload_id` * | path | Identificador devuelto al crear la subida |

| Respuesta | Descripción |
|---|---|
| `200` | Estado actual — `id`, `name`, `size`, `received`, `chunk_size` |
| `401` | Sesión no iniciada — `error` |
| `404` | La subida o la carpeta no existe, o pertenece a otro usuario — `error` |

## `PUT /api/uploads/{upload_id}`

**Enviar una parte.** Añade el cuerpo de la petición (binario) al final del fichero temporal. `offset` debe ser igual
a los bytes ya recibidos; si no, responde 409 con el valor correcto. El tamaño de la petición está
limitado por `server.max_upload_mb`.

Autenticación: `csrf`, `session`

| Parámetro | En | Descripción |
|---|---|---|
| `upload_id` * | path | Identificador devuelto al crear la subida |
| `offset` * | query | Posición en bytes donde empieza esta parte |

Cuerpo (`application/octet-stream`): datos binarios.

| Respuesta | Descripción |
|---|---|
| `200` | Parte guardada — `received` |
| `400` | Petición no válida (token CSRF, nombre, tamaño u offset) — `error` |
| `401` | Sesión no iniciada — `error` |
| `403` | Sin permiso de subida en esa carpeta (rol o carpeta de solo lectura) — `error` |
| `404` | La subida o la carpeta no existe, o pertenece a otro usuario — `error` |
| `409` | El offset no coincide con lo recibido — `error`, `received` |
| `413` | La parte supera `server.max_upload_mb` — `error` |

## `DELETE /api/uploads/{upload_id}`

**Cancelar una subida.** Borra el fichero temporal.

Autenticación: `csrf`, `session`

| Parámetro | En | Descripción |
|---|---|---|
| `upload_id` * | path | Identificador devuelto al crear la subida |

| Respuesta | Descripción |
|---|---|
| `204` | Subida cancelada |
| `401` | Sesión no iniciada — `error` |
| `404` | La subida o la carpeta no existe, o pertenece a otro usuario — `error` |

## `POST /api/uploads/{upload_id}/complete`

**Finalizar una subida.** Con todos los bytes recibidos, renombra de forma atómica el fichero temporal al nombre final.
Nunca sobrescribe: si el nombre existe, añade ` (1)`, ` (2)`…

Autenticación: `csrf`, `session`

| Parámetro | En | Descripción |
|---|---|---|
| `upload_id` * | path | Identificador devuelto al crear la subida |

| Respuesta | Descripción |
|---|---|
| `200` | Archivo guardado — `name`, `size` |
| `401` | Sesión no iniciada — `error` |
| `403` | Sin permiso de subida en esa carpeta (rol o carpeta de solo lectura) — `error` |
| `404` | La subida o la carpeta no existe, o pertenece a otro usuario — `error` |
| `409` | Faltan bytes por recibir — `error`, `received` |

`*` = obligatorio.

# Monitorización (Prometheus)

StorageWeb publica métricas en el formato de Prometheus en `/metrics`, para verlas en Grafana o avisar con Alertmanager. Están **desactivadas** por defecto.

## Activarlas

En *Sistema → Monitorización*:

| Ajuste | Para qué |
|---|---|
| `metrics.enabled` | Publicar `/metrics`. Desactivadas, la dirección responde 404, como si no existiera. |
| `metrics.token` | Token que envía Prometheus (`Authorization: Bearer <token>`), de al menos 16 caracteres. Nunca se muestra en la web; vacío al guardar = se conserva. |
| `metrics.allowed_networks` | IPs o redes (CIDR) desde las que se puede leer **sin** token. |

Sin token ni redes, solo se pueden leer desde el propio servidor (`127.0.0.1`). Con token, también el servidor tiene que enviarlo. Un token equivocado responde 403 y cuenta para el [bloqueo de IPs](seguridad.md), como un token de API equivocado. Detrás de un proxy inverso, la IP es la del cliente que da el proxy (`server.behind_proxy`).

También en `config.json` o con variables de entorno (`STORAGEWEB_METRICS__TOKEN`…), y entonces quedan bloqueados en la web.

## Prometheus

```yaml
scrape_configs:
  - job_name: storageweb
    scheme: https
    metrics_path: /metrics
    authorization:
      credentials: "<el token de metrics.token>"
    static_configs:
      - targets: ["files.midominio.com"]
```

## Qué se publica

| Métrica | Tipo | Qué es |
|---|---|---|
| `storageweb_info{version}` | gauge | Versión de StorageWeb (siempre 1). |
| `storageweb_start_time_seconds` | gauge | Cuándo arrancó el proceso. |
| `storageweb_http_requests_total{endpoint,method,code}` | counter | Peticiones por ruta, método y código de respuesta (los errores son los `code` 4xx y 5xx). |
| `storageweb_http_request_duration_seconds{endpoint}` | summary | Tiempo de respuesta por ruta (`_sum` / `_count` = media). |
| `storageweb_events_total{action}` | counter | Eventos de la [auditoría](../referencia/auditoria.md): `login`, `login_failed`, `upload`, `download`, `delete`… |
| `storageweb_upload_bytes_total{via}` | counter | Bytes subidos por la web, la API o la unidad de red (`web`, `api`, `webdav`). |
| `storageweb_download_bytes_total{via}` | counter | Bytes descargados (`web`, `webdav`). |
| `storageweb_quota_rejections_total` | counter | Escrituras rechazadas porque no cabían en la cuota. |
| `storageweb_audit_forward_errors_total` | counter | Eventos de auditoría que no se pudieron reenviar al syslog o al fichero ([reenvío a un SIEM](seguridad.md#reenviar-la-auditoria-a-un-siem)). |
| `storageweb_audit_forward_dropped_total` | counter | Eventos de auditoría no reenviados porque la cola estaba llena (en la base de datos sí están). |
| `storageweb_users{source,state}` | gauge | Cuentas por origen y estado (`enabled`, `disabled`). |
| `storageweb_sessions` | gauge | Sesiones web abiertas. |
| `storageweb_api_tokens` | gauge | Tokens de API vigentes. |
| `storageweb_ip_bans` | gauge | IPs o redes bloqueadas en vigor. |
| `storageweb_folder_used_bytes{folder}` | gauge | Lo que ocupa cada carpeta compartida. |
| `storageweb_folder_quota_bytes{folder}` | gauge | Su cuota (`0` = sin cuota). |
| `storageweb_folder_free_bytes{folder}` | gauge | Espacio libre donde está, si se sabe (disco del servidor). |
| `storageweb_location_up{location,type}` | gauge | Si cada ubicación remota respondió en su última comprobación (1/0). |
| `storageweb_location_last_check_timestamp_seconds{location}` | gauge | Cuándo se comprobó. |
| `storageweb_maintenance_last_run_timestamp_seconds{task}` | gauge | Cuándo corrió cada tarea de mantenimiento. |
| `storageweb_backups`, `storageweb_backup_last_timestamp_seconds` | gauge | Copias guardadas y fecha de la más reciente. |
| `storageweb_database_size_bytes` | gauge | Tamaño de la base de datos. |
| `storageweb_alerts{level}` | gauge | Avisos del Resumen de la administración, por nivel (`danger`, `warn`, `info`). |

Leer `/metrics` nunca recorre carpetas ni se conecta a nada, para responder al momento. Lo caro lo hace una tarea de mantenimiento cada 10 minutos mientras las métricas estén activas: mide lo que ocupa cada carpeta compartida y prueba cada ubicación remota. Por eso esas métricas aparecen unos minutos después de activarlas.

Los contadores (`_total`) son del proceso: empiezan en 0 al arrancar el servicio, como espera Prometheus (`rate()` lo tiene en cuenta).

## Alertas de ejemplo

```yaml
groups:
  - name: storageweb
    rules:
      - alert: StorageWebCaido
        expr: up{job="storageweb"} == 0
        for: 5m
      - alert: StorageWebErrores
        expr: sum(rate(storageweb_http_requests_total{code=~"5.."}[5m])) > 0.1
        for: 10m
      - alert: StorageWebUbicacionCaida
        expr: storageweb_location_up == 0
        for: 20m
      - alert: StorageWebSinCopias
        expr: time() - storageweb_backup_last_timestamp_seconds > 2 * 86400
      - alert: StorageWebAvisos
        expr: storageweb_alerts{level="danger"} > 0
        for: 30m
```

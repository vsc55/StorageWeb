# Solución de problemas

## Dónde mirar

| | |
|---|---|
| Log del servicio | `journalctl -u storageweb -f` · OpenRC: `/var/log/storageweb/storageweb.log` · Docker: `docker logs -f storageweb` |
| Estado | `curl -s http://127.0.0.1:8080/healthz` → `{"status": "ok", "version": "…"}` |
| Configuración efectiva | `storageweb-admin check-config` y *Sistema → Información → Configuración efectiva* |
| Qué es esta instalación | *Sistema → Información*: versión, cómo se ejecuta (servicio de Windows, contenedor, systemd…), desde cuándo, máquina, hora del servidor, base de datos (versión del esquema), carpetas (si existen, si se pueden escribir y el espacio libre) y las bibliotecas instaladas. **Descargar el informe** (texto o JSON, sin secretos) para adjuntarlo a una incidencia |
| Quién hizo qué | `storageweb-admin audit --limit 50 [--user ana]` o *Seguridad → Auditoría* |

## Inicio de sesión

**Introduzco bien la contraseña y vuelvo a la página de login, sin error.**
: La cookie de sesión no llega: `session.cookie_secure = true` y se accede por HTTP. Usa HTTPS o, solo para pruebas en localhost, pon `cookie_secure` a `false`.

**«Demasiados intentos fallidos».**
: Bloqueo temporal (`security.lockout_minutes`) por IP o por usuario. Espera, o reinicia el servicio (el bloqueo está en memoria). Si todos los usuarios aparecen bloqueados a la vez, puede que `behind_proxy` esté desactivado detrás de un proxy: todas las peticiones parecen venir de la IP del proxy.

**Nadie puede entrar después de cambiar los ajustes web** (por ejemplo, desactivaste el login local y Entra ID está mal configurado).
: `sudo storageweb-admin settings-reset` descarta los ajustes web y vuelve a `config.json` sin reiniciar.

**No hay ningún administrador.**
: `sudo storageweb-admin user-add admin --role admin`, o promociona uno existente con `user-set <usuario> --role admin`.

**Errores de Microsoft Entra ID.**
: Ver la tabla de errores en [Entra ID](entra-id.md#errores-frecuentes).

**El login con usuarios del sistema (PAM) siempre falla.**
: Comprueba estas tres cosas: que está instalado `python-pam`; que el usuario del servicio puede leer `/etc/shadow` (grupo `shadow`); y que el usuario pertenece a `allowed_groups`, si lo definiste. El log indica `falta el paquete python-pam` o `no pertenece a allowed_groups`.

## Archivos

**«La carpeta configurada no existe en el servidor».**
: La ruta de la carpeta compartida no existe. Créala con permisos para el usuario del servicio, o activa `storage.create_shares`.

**«El servicio no tiene permisos para leer esta carpeta»** o errores al escribir.
: El usuario `storageweb` (uid 10001 en Docker) no tiene permisos sobre la ruta. Corrige el propietario o las ACL. Con systemd, comprueba además que la ruta está en `ReadWritePaths` y no la oculta `ProtectHome` (`systemctl edit storageweb`).

**`413 Request Entity Too Large` al subir.**
: Lo devuelve el proxy: en nginx, `client_max_body_size`; en Apache, `LimitRequestBody` (desde la 2.4.54 limita a 1 GB por defecto). Debe ser al menos 33 MB para las subidas por partes, y al menos `server.max_upload_mb` para la subida sin JavaScript y la unidad de red.

**«El archivo supera el máximo permitido».**
: `storage.max_file_size_mb`.

**«No hay espacio suficiente en el servidor» (507).**
: El disco no tiene espacio para el archivo más un margen de 64 MB.

**Las descargas grandes se cortan en torno a 1 GB.**
: Faltan `proxy_buffering off` y `proxy_max_temp_file_size 0` en nginx.

**Con Apache, las subidas lentas fallan a los 20 s (408 o conexión cortada).**
: `mod_reqtimeout` corta un cuerpo de petición que llega despacio. Pon `RequestReadTimeout header=20-40,MinRate=500 body=300,MinRate=1` (está en la plantilla).

**Quedan ficheros `.sw-upload-*.part`.**
: Son subidas interrumpidas. Se borran solos a las 24 horas de inactividad (`storage.upload_stale_hours`, en *Sistema → Archivos*), cuando alguien inicia otra subida. Se pueden borrar a mano con el servicio en marcha.

## Servicio

**No arranca: `Error de configuración: …`.**
: El mensaje indica la opción incorrecta. Valida con `storageweb-admin check-config`.

**Docker: el contenedor queda `unhealthy`.**
: Revisa `docker logs`. Si cambiaste el puerto en `config.json`, define también `STORAGEWEB_PORT` para que el healthcheck use el mismo.

**`database is locked`.**
: Otro proceso tiene la base de datos bloqueada mucho tiempo, por ejemplo una copia manual con `sqlite3`. Usa `storageweb backup`, que no bloquea.

# HTTPS con nginx o Apache

StorageWeb escucha en HTTP en `127.0.0.1:8080` y espera un **proxy inverso con HTTPS** delante. HTTPS es imprescindible por tres motivos:

- la cookie de sesión solo se envía por HTTPS (`session.cookie_secure = true`);
- Microsoft Entra ID solo acepta URLs de vuelta HTTPS (salvo `localhost`);
- las contraseñas y los archivos viajan cifrados.

Hay plantillas listas para **nginx** y **Apache** (abajo); sirve cualquier otro proxy que envíe las cabeceras `X-Forwarded-*` y permita cuerpos grandes (ver *Otros proxies*).

## nginx

Los paquetes instalan la plantilla en `/usr/share/storageweb/nginx-storageweb.conf`. En el repositorio está en `packaging/nginx/storageweb.conf`. El instalador la copia con `install.sh --nginx`.

```bash
sudo cp /usr/share/storageweb/nginx-storageweb.conf /etc/nginx/sites-available/storageweb
sudo nano /etc/nginx/sites-available/storageweb          # server_name y certificados
sudo ln -s /etc/nginx/sites-available/storageweb /etc/nginx/sites-enabled/
sudo certbot --nginx -d files.midominio.com
sudo nginx -t && sudo systemctl reload nginx
```

### Directivas importantes

| Directiva | Valor | Por qué |
|---|---|---|
| `client_max_body_size` | ≥ `server.max_upload_mb` | Tamaño máximo de petición. Las subidas desde el navegador van en partes de hasta 32 MB, pero la subida sin JavaScript y la [unidad de red](../uso/unidad-de-red.md) (WebDAV) usan una sola petición por archivo. |
| `proxy_request_buffering off` | | Las subidas pasan directas a la aplicación, sin copia temporal en nginx. |
| `proxy_buffering off` y `proxy_max_temp_file_size 0` | | Descargas en streaming sin límite (por defecto nginx guarda hasta 1 GB en temporal). |
| `proxy_read_timeout`, `proxy_send_timeout` | `300s` | Son tiempos de inactividad, no de duración total. |
| `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host` | | La aplicación los usa con `server.behind_proxy = true` para conocer la IP real (auditoría y bloqueo de intentos) y generar URLs HTTPS. |
| `proxy_set_header X-Forwarded-Prefix ""` | | La subruta solo la dice el proxy: vacía, nginx no la envía y se pierde la que pudiera mandar el cliente (que la aplicación usaría en sus enlaces). Bajo una subruta, pon la tuya. |
| `ssl_protocols TLSv1.2 TLSv1.3` | | Solo versiones seguras de TLS (es lo que hace nginx por defecto desde la 1.23.4; la línea cubre versiones anteriores). |
| `server_tokens off` | | No anuncia la versión de nginx en las páginas de error ni en la cabecera `Server`. |
| `access_log`, `error_log` | `/var/log/nginx/storageweb.*` | Logs propios del sitio, sin mezclarlos con los de otros. |

## Apache

Apache 2.4 con `mod_proxy`. Los paquetes instalan la plantilla en `/usr/share/storageweb/apache-storageweb.conf` (en el repositorio, `packaging/apache/storageweb.conf`), y el instalador la copia y activa los módulos con `install.sh --apache`.

Debian / Ubuntu:

```bash
sudo cp /usr/share/storageweb/apache-storageweb.conf /etc/apache2/sites-available/storageweb.conf
sudo nano /etc/apache2/sites-available/storageweb.conf        # ServerName y certificados
sudo a2enmod proxy proxy_http ssl headers http2 reqtimeout rewrite
sudo a2ensite storageweb
sudo certbot --apache -d files.midominio.com
sudo apachectl configtest && sudo systemctl reload apache2
```

RHEL / Fedora / Rocky: copia la plantilla a `/etc/httpd/conf.d/storageweb.conf` (paquetes `httpd` y `mod_ssl`; los módulos ya vienen cargados), cambia las rutas de los logs a `/var/log/httpd/`, `sudo certbot --apache -d files.midominio.com` y `sudo systemctl reload httpd`. Con SELinux, Apache necesita permiso para conectar con la aplicación: `sudo setsebool -P httpd_can_network_connect 1`.

### Directivas importantes

| Directiva | Valor | Por qué |
|---|---|---|
| `LimitRequestBody` | ≥ `server.max_upload_mb` (en bytes) | Tamaño máximo de petición, como `client_max_body_size` en nginx. **Desde Apache 2.4.54 el límite por defecto es 1 GB**: sin esta línea, la subida sin JavaScript y la unidad de red (WebDAV) fallan con 413 en archivos grandes. Como mucho 2147483647; `0` = sin límite. |
| `RequestReadTimeout … body=300,MinRate=1` | | `mod_reqtimeout` corta por defecto a los 20 s una petición cuyo cuerpo llega despacio: una subida lenta fallaría. |
| `Timeout`, `ProxyTimeout` | `300` | Tiempos de inactividad con el cliente y con la aplicación. |
| `ProxyPass … nocanon` y `AllowEncodedSlashes NoDecode` | | La ruta llega tal cual a la aplicación, que la valida. Sin ellas, Apache rechaza o cambia nombres con `%`, `#`, `?` o barras codificadas. |
| `ProxyPreserveHost On` | | La aplicación ve el nombre público; WebDAV lo necesita para `COPY` y `MOVE` (comprueba que el destino es el mismo servidor). |
| `RequestHeader set X-Forwarded-Proto "https"` | | `X-Forwarded-For` y `X-Forwarded-Host` los añade `mod_proxy`; el esquema hay que ponerlo. Sin él, las URLs para Entra ID saldrían con `http://`. |
| `RequestHeader unset X-Forwarded-Prefix` | | La subruta solo la dice el proxy: se quita la que pudiera mandar el cliente (`mod_proxy` la dejaría pasar y la aplicación la usaría en sus enlaces). Bajo una subruta, `RequestHeader set X-Forwarded-Prefix "/archivos"`. |
| `SSLProtocol -all +TLSv1.2 +TLSv1.3`, `SSLHonorCipherOrder off` | | Solo versiones seguras de TLS. Con `certbot --apache` puedes cambiarlas por `Include /etc/letsencrypt/options-ssl-apache.conf`, que certbot mantiene al día. |
| `ServerSignature Off` (y `ServerTokens Prod` en la configuración global) | | No anunciar la versión de Apache ni del sistema. `ServerTokens` no vale dentro de un `VirtualHost`: en Debian va en `/etc/apache2/conf-available/security.conf`. |
| `ErrorLog`, `CustomLog` | `/var/log/apache2/storageweb-*.log` | Logs propios del sitio. En RHEL la carpeta es `/var/log/httpd/`: cámbiala o Apache no arrancará. |
| `Protocols h2 http/1.1` | | HTTP/2. Con `mpm_prefork` (habitual si está instalado `mod_php`) no tiene efecto y Apache no avisa: compruébalo con `apachectl -V \| grep MPM`; para usar `mpm_event` en Debian, `a2dismod mpm_prefork && a2enmod mpm_event`. |
| `RewriteRule ^ https://%{SERVER_NAME}%{REQUEST_URI} [R=301,L]` (puerto 80) | | Redirige todo HTTP a HTTPS con el mismo nombre por el que entró el usuario (`ServerName` o cualquier `ServerAlias`, sin repetir el FQDN), la misma ruta y la misma consulta. `%{SERVER_NAME}` y no `%{HTTP_HOST}`, que arrastraría el puerto si el cliente lo envía. |

Antes de usarla en producción: `apachectl configtest`, sube un archivo grande y prueba la [unidad de red](../uso/unidad-de-red.md).

Subidas y descargas van en streaming sin configurar nada (Apache no guarda las descargas en disco, a diferencia de nginx). No actives `proxy-sendchunked`: la aplicación necesita el tamaño de la subida para rechazar de entrada un archivo demasiado grande o sin espacio. Los métodos de WebDAV (`PROPFIND`, `MOVE`, `LOCK`…) pasan por el proxy sin más; no actives `mod_dav` para esa ruta.

!!! danger "behind_proxy"
    Activa `server.behind_proxy` **solo** si la aplicación es accesible únicamente a través del proxy (`server.host = 127.0.0.1`). Si no, un cliente podría falsificar `X-Forwarded-For` y saltarse el bloqueo de intentos por IP.

## Dirección pública (FQDN)

Detrás de un proxy, la aplicación no sabe por sí sola con qué nombre entran los usuarios. Indica el **FQDN** en `network.public_url` (en `config.json` o en *Sistema → Red y HTTPS*). Basta con el nombre; se asume HTTPS:

```json
"network": { "public_url": "files.midominio.com" }
```

Si hace falta, con puerto o subruta: `files.midominio.com:8443` o `www.midominio.com/archivos`. Escribe `http://` delante solo para pruebas en local (`http://localhost:8080`).

Se usa para las URLs que salen hacia fuera: la dirección de vuelta de Entra ID (que siempre se calcula de aquí) y la de salida de Microsoft. Si está vacía, se usa el host de cada petición, que vale cuando solo se entra por un nombre y el proxy envía `X-Forwarded-Host` y `X-Forwarded-Proto`.

## Varios proxies y subrutas

- **Proxies encadenados** (una CDN o un balanceador delante de nginx o Apache): pon `server.proxy_hops` al número de proxies. La aplicación toma la IP real y el esquema de la posición correcta de `X-Forwarded-*`, y no confía en valores añadidos por el cliente.
- **Servir bajo una subruta** (`https://www.midominio.com/archivos/`): el proxy debe enviar `X-Forwarded-Prefix: /archivos` y quitar ese prefijo al reenviar. Pon la ruta también en `network.public_url` (`www.midominio.com/archivos`). La página *Red y HTTPS* genera la configuración de nginx, Apache y Caddy para la subruta.

## Comprobar la configuración

*Sistema → Red y HTTPS* muestra cómo llega tu petición (esquema, host, subruta, IP del cliente y del proxy, cabeceras `X-Forwarded-*`) y avisa de los errores típicos:

| Aviso | Causa habitual |
|---|---|
| Cabeceras `X-Forwarded-*` con `behind_proxy` desactivado | Falta `server.behind_proxy: true`: la IP y el esquema son los del proxy. |
| `behind_proxy` activo sin `X-Forwarded-For` | Estás entrando sin pasar por el proxy. Si además escucha en `0.0.0.0`, cualquiera puede falsear su IP. |
| La dirección pública es HTTPS pero la petición llega como HTTP | El proxy no envía `X-Forwarded-Proto`. Las URLs para Entra ID saldrían con `http://`. |
| La dirección pública no es HTTPS | Entra ID solo acepta direcciones de vuelta HTTPS (salvo `localhost`). |
| `session.cookie_secure` desactivado con HTTPS | Actívalo en producción. |
| La Redirect URI de Entra ID no usa la dirección pública | Cambia una de las dos para que coincidan. |

La misma página tiene un ejemplo de nginx, Apache y Caddy rellenado con tus valores (nombre, puerto, subruta y tamaño máximo).

!!! note "¿Y HTTPS sin proxy?"
    StorageWeb usa Waitress, que no cifra. Delega HTTPS en un proxy: nginx o Apache con certbot, o Caddy, que obtiene y renueva el certificado solo. La cabecera HSTS se envía automáticamente cuando la petición llega por HTTPS.

## Otros proxies

Sirve cualquier proxy que envíe las cabeceras `X-Forwarded-*` y permita cuerpos grandes: Caddy, Traefik o HAProxy. Un ejemplo con Caddy:

```
files.midominio.com {
    request_body {
        max_size 2100MB
    }
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

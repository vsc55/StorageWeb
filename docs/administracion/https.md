# HTTPS con nginx

StorageWeb escucha en HTTP en `127.0.0.1:8080` y espera un **proxy inverso con HTTPS** delante. HTTPS es imprescindible por tres motivos:

- la cookie de sesión solo se envía por HTTPS (`session.cookie_secure = true`);
- Microsoft Entra ID solo acepta URLs de vuelta HTTPS (salvo `localhost`);
- las contraseñas y los archivos viajan cifrados.

## Configuración

Los paquetes instalan la plantilla en `/usr/share/storageweb/nginx-storageweb.conf`. En el repositorio está en `packaging/nginx/storageweb.conf`.

```bash
sudo cp /usr/share/storageweb/nginx-storageweb.conf /etc/nginx/sites-available/storageweb
sudo nano /etc/nginx/sites-available/storageweb          # server_name y certificados
sudo ln -s /etc/nginx/sites-available/storageweb /etc/nginx/sites-enabled/
sudo certbot --nginx -d files.midominio.com
sudo nginx -t && sudo systemctl reload nginx
```

## Directivas importantes

| Directiva | Valor | Por qué |
|---|---|---|
| `client_max_body_size` | ≥ `server.max_upload_mb` | Tamaño máximo de petición. Las subidas desde el navegador van en partes de hasta 32 MB, pero la subida sin JavaScript usa una sola petición. |
| `proxy_request_buffering off` | | Las subidas pasan directas a la aplicación, sin copia temporal en nginx. |
| `proxy_buffering off` y `proxy_max_temp_file_size 0` | | Descargas en streaming sin límite (por defecto nginx guarda hasta 1 GB en temporal). |
| `proxy_read_timeout`, `proxy_send_timeout` | `300s` | Son tiempos de inactividad, no de duración total. |
| `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host` | | La aplicación los usa con `server.behind_proxy = true` para conocer la IP real (auditoría y bloqueo de intentos) y generar URLs HTTPS. |

!!! danger "behind_proxy"
    Activa `server.behind_proxy` **solo** si la aplicación es accesible únicamente a través del proxy (`server.host = 127.0.0.1`). Si no, un cliente podría falsificar `X-Forwarded-For` y saltarse el bloqueo de intentos por IP.

## Otros proxies

Sirve cualquier proxy que envíe las cabeceras `X-Forwarded-*` y permita cuerpos grandes: Caddy, Traefik, HAProxy o Apache. Un ejemplo con Caddy:

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

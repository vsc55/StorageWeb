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

## Dirección pública (FQDN)

Detrás de un proxy, la aplicación no sabe por sí sola con qué nombre entran los usuarios. Indica el **FQDN** en `network.public_url` (en `config.json` o en *Sistema → Red y HTTPS*). Basta con el nombre; se asume HTTPS:

```json
"network": { "public_url": "files.midominio.com" }
```

Si hace falta, con puerto o subruta: `files.midominio.com:8443` o `www.midominio.com/archivos`. Escribe `http://` delante solo para pruebas en local (`http://localhost:8080`).

Se usa para las URLs que salen hacia fuera: la dirección de vuelta de Entra ID (si `auth.entra.redirect_uri` está vacía) y la de salida de Microsoft. Si está vacía, se usa el host de cada petición, que vale cuando solo se entra por un nombre y el proxy envía `X-Forwarded-Host` y `X-Forwarded-Proto`.

## Varios proxies y subrutas

- **Proxies encadenados** (una CDN o un balanceador delante de nginx): pon `server.proxy_hops` al número de proxies. La aplicación toma la IP real y el esquema de la posición correcta de `X-Forwarded-*`, y no confía en valores añadidos por el cliente.
- **Servir bajo una subruta** (`https://www.midominio.com/archivos/`): el proxy debe enviar `X-Forwarded-Prefix: /archivos` y quitar ese prefijo al reenviar. Pon la ruta también en `network.public_url` (`www.midominio.com/archivos`). La página *Red y HTTPS* genera la configuración de nginx y de Caddy para la subruta.

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

La misma página tiene un ejemplo de nginx y de Caddy rellenado con tus valores (nombre, puerto, subruta y tamaño máximo).

!!! note "¿Y HTTPS sin proxy?"
    StorageWeb usa Waitress, que no cifra. Delega HTTPS en un proxy: nginx con certbot, o Caddy, que obtiene y renueva el certificado solo. La cabecera HSTS se envía automáticamente cuando la petición llega por HTTPS.

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

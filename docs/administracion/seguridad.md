# Seguridad en producción

## Lista de comprobación

- [ ] **HTTPS** con un proxy inverso ([nginx](https.md)) y `session.cookie_secure = true`.
- [ ] `server.host = 127.0.0.1` y `server.behind_proxy = true`, de modo que la aplicación solo sea accesible a través del proxy.
- [ ] El cortafuegos solo expone 443 (y 80 para la redirección). El 8080 no debe ser accesible desde fuera.
- [ ] `/etc/storageweb/config.json` en `root:storageweb 0640`; contiene el `client_secret`.
- [ ] Al menos un admin con una contraseña larga, o mejor solo admins de Entra ID con MFA.
- [ ] Entra ID: *Assignment required* y App Roles; anota la caducidad del `client_secret`.
- [ ] Copias programadas y [restauración probada](copias-seguridad.md).
- [ ] La auditoría se revisa periódicamente (*Seguridad → Auditoría* o `storageweb-admin audit`).
- [ ] Actualizaciones del sistema y de StorageWeb al día.
- [ ] Límites ajustados: `storage.max_file_size_mb`, `security.max_login_failures`, `client_max_body_size`.

## Qué protege StorageWeb

| Riesgo | Control |
|---|---|
| Robo de sesión | Cookie `HttpOnly`, `Secure` y `SameSite=Lax`, firmada con `secret_key`; caducidad configurable |
| CSRF | Token por sesión en todos los POST/PUT/DELETE |
| Fuerza bruta | Bloqueo temporal por IP y por usuario; **bloqueo automático de IPs** con muchas infracciones; comparación en tiempo constante |
| Sesiones robadas o abandonadas | Sesiones registradas en el servidor: se ven y se cierran en *Personas → Sesiones y tokens*; desactivar un usuario o cambiarle la contraseña las cierra todas |
| Scripts con la contraseña | Tokens de API personales (`sw_…`) con alcance de lectura o de lectura y escritura, caducidad y revocación; solo se guarda su hash |
| Salir de la carpeta asignada | Se rechazan `..`, rutas absolutas y symlinks que salen de la raíz; se comprueba en cada petición |
| Nombres de archivo maliciosos | Saneado, que conserva acentos, rechaza nombres reservados de Windows y limita a 255 bytes |
| XSS / clickjacking | Plantillas con escape automático, CSP sin `unsafe-inline`, `X-Frame-Options: DENY`, `nosniff` |
| Escalada en el servidor | Usuario sin privilegios, systemd con `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp` y `UMask=0007` |
| Tokens SSO falsificados | `state`, `nonce`, PKCE y validación de `iss`, `aud`, `exp` y `tid` |
| Suplantación entre orígenes | Una cuenta de Entra nunca se vincula a una local con el mismo nombre |

## Bloqueo de IPs

*Seguridad → Reglas de bloqueo* e *IPs bloqueadas*:

- **Automático:** con `security.ipban_threshold` infracciones (contraseña errónea, CSRF no válido, token de API no válido) en `ipban_window_minutes`, la IP queda bloqueada `ipban_minutes` (0 = hasta que la quites). Las direcciones de loopback nunca se bloquean: sin `server.behind_proxy`, todo el tráfico de un proxy local llega como 127.0.0.1.
- **Manual:** bloquea una IP o una red CIDR, con duración. No puedes bloquear la dirección que estás usando.
- **Lista blanca:** redes que nunca se bloquean (la oficina, la VPN).
- **Rescate** si te bloqueas: `sudo storageweb-admin ip-unban --all` (o `ip-unban <ip>`); `ip-list` muestra las reglas.

## Sesiones y tokens de API

- *Personas → Sesiones y tokens* muestra quién ha iniciado sesión (navegador, IP, última actividad) y todos los tokens de API. Puedes cerrar una sesión, todas las de un usuario o todas menos la tuya, y revocar tokens. Desde el servidor: `storageweb-admin sessions-close <usuario>` o `--all`.
- Cada usuario ve las suyas en *Mi perfil* y puede cerrar las demás. Cambiar la contraseña cierra las otras sesiones.
- Los tokens de API se crean en *Mi perfil → Tokens de API*. Solo sirven para listar, descargar y subir archivos; nunca para la administración ni el perfil. Se desactivan para todos con `security.api_tokens = false`.

```bash
TOKEN=sw_…
curl -H "Authorization: Bearer $TOKEN" https://files.midominio.com/f/home/            # listado en JSON
curl -H "Authorization: Bearer $TOKEN" -O https://files.midominio.com/download/home/informe.pdf
curl -H "Authorization: Bearer $TOKEN" -F files=@informe.pdf https://files.midominio.com/upload/home/   # alcance de escritura
```

## Lo que NO hace (todavía)

Conviene saberlo para cubrirlo por otros medios:

- **Antivirus:** no analiza los archivos subidos. Usa ClamAV sobre `/srv/storageweb` si lo necesitas.
- **Cifrado en reposo:** usa cifrado de disco (LUKS) o del sistema de ficheros.
- **Cuotas:** no hay cuota por usuario; usa cuotas del sistema de ficheros o un tamaño máximo por archivo.
- **Bloqueo de intentos por usuario en memoria:** se reinicia al reiniciar el servicio. El bloqueo de IPs sí se guarda en la base de datos.
- **Expiración del cambio de rol:** un usuario desactivado pierde la sesión en su siguiente petición. Un cambio de rol se aplica también en la siguiente petición.

El análisis completo está en el [modelo de seguridad](../arquitectura/seguridad.md). Para informar de una vulnerabilidad, consulta la [política de seguridad](../proyecto/seguridad.md).

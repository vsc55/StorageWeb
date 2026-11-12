# Seguridad en producción

## Lista de comprobación

- [ ] **HTTPS** con un proxy inverso ([nginx](https.md)) y `session.cookie_secure = true`.
- [ ] `server.host = 127.0.0.1` y `server.behind_proxy = true`, de modo que la aplicación solo sea accesible a través del proxy.
- [ ] El cortafuegos solo expone 443 (y 80 para la redirección). El 8080 no debe ser accesible desde fuera.
- [ ] `/etc/storageweb/config.json` en `root:storageweb 0640`; contiene el `client_secret`.
- [ ] Al menos un admin con una contraseña larga, o mejor solo admins de Entra ID con MFA.
- [ ] Entra ID: *Assignment required* y App Roles; anota la caducidad del `client_secret`.
- [ ] Copias programadas y [restauración probada](copias-seguridad.md).
- [ ] La auditoría se revisa periódicamente (*Administración → Auditoría* o `storageweb-admin audit`).
- [ ] Actualizaciones del sistema y de StorageWeb al día.
- [ ] Límites ajustados: `storage.max_file_size_mb`, `security.max_login_failures`, `client_max_body_size`.

## Qué protege StorageWeb

| Riesgo | Control |
|---|---|
| Robo de sesión | Cookie `HttpOnly`, `Secure` y `SameSite=Lax`, firmada con `secret_key`; caducidad configurable |
| CSRF | Token por sesión en todos los POST/PUT/DELETE |
| Fuerza bruta | Bloqueo temporal por IP y por usuario; comparación en tiempo constante |
| Salir de la carpeta asignada | Se rechazan `..`, rutas absolutas y symlinks que salen de la raíz; se comprueba en cada petición |
| Nombres de archivo maliciosos | Saneado, que conserva acentos, rechaza nombres reservados de Windows y limita a 255 bytes |
| XSS / clickjacking | Plantillas con escape automático, CSP sin `unsafe-inline`, `X-Frame-Options: DENY`, `nosniff` |
| Escalada en el servidor | Usuario sin privilegios, systemd con `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp` y `UMask=0007` |
| Tokens SSO falsificados | `state`, `nonce`, PKCE y validación de `iss`, `aud`, `exp` y `tid` |
| Suplantación entre orígenes | Una cuenta de Entra nunca se vincula a una local con el mismo nombre |

## Lo que NO hace (todavía)

Conviene saberlo para cubrirlo por otros medios:

- **Antivirus:** no analiza los archivos subidos. Usa ClamAV sobre `/srv/storageweb` si lo necesitas.
- **Cifrado en reposo:** usa cifrado de disco (LUKS) o del sistema de ficheros.
- **Cuotas:** no hay cuota por usuario; usa cuotas del sistema de ficheros o un tamaño máximo por archivo.
- **Bloqueo de intentos en memoria:** se reinicia al reiniciar el servicio, y no se comparte si hubiera varias instancias.
- **Expiración del cambio de rol:** un usuario desactivado pierde la sesión en su siguiente petición. Un cambio de rol se aplica también en la siguiente petición.

El análisis completo está en el [modelo de seguridad](../arquitectura/seguridad.md). Para informar de una vulnerabilidad, consulta la [política de seguridad](../proyecto/seguridad.md).

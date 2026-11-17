# Registro de cambios

Todos los cambios relevantes del proyecto. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). El proyecto sigue [versionado semántico](https://semver.org/lang/es/).

Secciones de cada versión: *Añadido*, *Cambiado*, *Obsoleto*, *Eliminado*, *Corregido*, *Seguridad*. También, cuando proceda, *Cambios incompatibles* y *Notas de actualización*.

## [Sin publicar]

## [0.1.0] - 2026-11-17

Primera versión publicada. Es la serie **0.x**, en desarrollo: entre versiones menores (0.1 → 0.2) puede haber cambios incompatibles en la configuración, la CLI, la API o las copias de seguridad, y se avisarán aquí.

### Añadido

**Archivos**

- Servidor web de archivos (Flask + Waitress) con explorador en tres columnas (árbol de carpetas, lista y detalle): subir (por partes y reanudable), descargar (con `Range`), crear carpetas, renombrar y borrar, selección múltiple, filtro y orden por nombre, tamaño o fecha.
- **Mover y copiar**, también arrastrando y entre carpetas de almacenamientos distintos, sin sobrescribir nunca; **descargar como ZIP** varios elementos o una carpeta (generado al vuelo, ZIP64); **buscar por nombre** en todas tus carpetas, sin distinguir mayúsculas ni tildes.
- Carpeta personal y **carpetas compartidas** por usuario o grupo, con acceso de solo lectura por grupo o por usuario (`*` para todos).
- **Cuotas** para las carpetas personales (por defecto, por grupo y por usuario) y por carpeta compartida, que bloquean lo que no quepa (`storage.quota_enforce`) o solo avisan, y **espacio libre** del almacenamiento en el explorador.
- **Ocultos para todos** (`storage.hidden`): patrones como los de `.gitignore` de lo que no se lista, no se abre ni se puede crear.
- **Almacenamiento externo** sin montarlo: S3 (Amazon, MinIO, Wasabi, R2…), SMB, SFTP, WebDAV, FTP/FTPS y Azure Blob Storage, además del disco del servidor. Ubicaciones con nombre, prueba de conexión y secretos ocultos. Extras `storageweb[s3]`, `[smb]`, `[sftp]` y `[azure]`.

**Acceso desde otros programas**

- **Unidad de red (WebDAV)** en `/dav/` para Windows, macOS, Linux, rclone, Cyberduck o WinSCP, con los mismos permisos que la web, escritura condicional (`If-Match`) y cuota publicada (RFC 4331).
- **Tokens de API personales** (`Authorization: Bearer sw_…`) de lectura o de lectura y escritura, con caducidad, rotación y revocación; los listados responden en JSON.
- **Extensión de Visual Studio Code** (`clients/vscode`): sincroniza en los dos sentidos la carpeta del espacio de trabajo con una de StorageWeb, con conflictos guardados como copia, papelera, exclusiones (`.storagewebignore` y `.gitignore`) y protección contra bucles; navegar, abrir y guardar directamente en varios servidores. Sin dependencias; el `.vsix` va en cada release con su propia versión (la 0.4.2 en esta).
- **Conectar aplicaciones iniciando sesión en el navegador** (`/connect/<aplicación>`, OAuth con PKCE): la aplicación recibe su token sin copiarlo.

**Usuarios e inicio de sesión**

- Usuarios **locales**, del sistema (**PAM**) y de **Microsoft Entra ID** (OAuth2/OIDC propio o MSAL). Los métodos de inicio de sesión se registran solos (ADR 0015).
- Pantalla de inicio de sesión con imagen al lado: cinco ilustraciones en el color principal, una al azar o una propia. Con Entra ID activo, su botón va primero y la cuenta local queda plegada.
- **Entra ID** completo desde la web: asistente, registro de la aplicación con un botón, *Probar conexión* (con todos los permisos), *Reparar automáticamente*, aviso y renovación del secreto, nombres de los grupos, entrada directa (`auth.entra.auto_login`), revisión periódica del directorio (cuentas borradas o desactivadas, grupos y rol), usuarios con más de 200 grupos, cierre de sesión de canal frontal y cambio de UPN.
- Roles `admin` y `user`, permisos del rol, **grupos** locales, de Entra ID y del sistema con miembros manuales y sincronizados, grupo **Administradores** de serie y **matriz de accesos** grupos × carpetas.
- Activar y desactivar usuarios de cualquier origen; identificador público (UUID) en las direcciones de la administración.
- **Sesiones en el servidor**: quién está conectado, cerrar sesiones sueltas, por usuario o inactivas. **Mi perfil**: nombre, email, idioma, tema, contraseña, tokens y unidad de red.

**Seguridad**

- Bloqueo tras intentos fallidos y **bloqueo de IPs** automático por infracciones, manual por IP o red, con lista blanca.
- **Secretos cifrados** en la base de datos (AES-256-GCM) con una clave propia (`secrets.key` o `STORAGEWEB_SECRETS_KEY`); comandos `encrypt-secret` y `rotate-secrets-key`.
- **Auditoría** de las acciones relevantes, con filtros, paginación y exportación a CSV.
- CSRF, CSP sin scripts ni estilos en línea, rutas limpiadas igual en todos los almacenamientos y batería de ataques de rutas en los tests.

**Administración**

- Administración por **zonas** (Personas, Acceso, Seguridad, Sistema), **Resumen** con avisos y su acción, y **buscador** (Ctrl+K) que lleva al ajuste exacto.
- **Configuración por capas**, campo a campo: valores predeterminados < web < `config.json` < variables `STORAGEWEB_*`. Lo fijado en fichero o entorno queda bloqueado en la web; *Restablecer* por campo; **perfiles de ajustes** para varias instancias sobre la misma base de datos; carpetas compartidas, ubicaciones y cuotas de grupo como entidades propias (ADR 0017 y 0018).
- **Marca**: color principal, logo propio (o el cubo de serie), favicon e imagen del inicio de sesión.
- **Red y HTTPS**: dirección pública (`network.public_url`), proxies encadenados (`server.proxy_hops`, con las cabeceras `X-Forwarded-*` validadas por la aplicación), subrutas (`X-Forwarded-Prefix`) y diagnóstico de cómo llega la petición, con ejemplos de nginx, Apache y Caddy.
- **Mantenimiento**: retención de la auditoría, compactación, **copias de seguridad** desde la web (crear, descargar, subir, borrar y automáticas) y **restaurar** con el servicio en marcha.
- **Métricas para Prometheus** en `/metrics`.

**Interfaz**

- Español e inglés, según la preferencia del usuario o el navegador; tema Sistema, Claro u Oscuro; adaptable al móvil; ventanas de confirmación propias y avisos emergentes. Las acciones básicas funcionan sin JavaScript.

**Instalación**

- Paquetes `.deb` y `.rpm` (amd64 y arm64) con las dependencias incluidas, instalador `install.sh`, imagen **Docker** multi-arquitectura en GHCR, overlay de **Gentoo** y plantillas de **nginx** y **Apache**.
- CLI `storageweb` (servidor, usuarios, sesiones, IPs, copias y restauración, secretos, ajustes) y timer de systemd para copias.
- `GET /healthz` y documentación en MkDocs con capturas de pantalla reales (de una demostración con datos inventados, `tools/screenshots/`), diagramas de flujo y la referencia de configuración, CLI y API generada desde el código.
- Releases en GitHub con el texto de su sección de este registro, paquetes, imagen Docker, documentación en GitHub Pages y la extensión de VS Code.

### Notas

- Licencia **GPL-3.0 o posterior** (`LICENSE`): quien distribuya StorageWeb, modificado o no, tiene que hacerlo con el código fuente y bajo la misma licencia.
- La interfaz sale en **inglés** por defecto si el navegador no pide otro idioma: para español, *System → General and branding* o `"default_locale": "es"` en `config.json`.

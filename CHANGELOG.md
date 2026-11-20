# Registro de cambios

Todos los cambios relevantes del proyecto. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). El proyecto sigue [versionado semántico](https://semver.org/lang/es/).

Secciones de cada versión: *Añadido*, *Cambiado*, *Obsoleto*, *Eliminado*, *Corregido*, *Seguridad*. También, cuando proceda, *Cambios incompatibles* y *Notas de actualización*.

## [Sin publicar]

### Añadido

- **Verificación en dos pasos (TOTP)** para las cuentas que entran con contraseña (locales y PAM): un código de una aplicación de autenticación además de la contraseña. Se activa en *Mi perfil* con un QR (o la clave) y da diez **códigos de recuperación** de un solo uso. La política `security.mfa_required` (*Seguridad → Inicio de sesión*: nadie, administradores o todos) la exige; quien la debe y no la tiene la configura al entrar, así que nunca deja fuera a nadie. Hasta el código no hay sesión, cada código vale una vez y los fallos cuentan como contraseñas erróneas. Con ella, la unidad de red solo admite tokens. Un administrador la quita en la ficha del usuario (y `storageweb-admin mfa-reset`); `mfa-status` lista quién la tiene. La semilla se guarda cifrada, viaja en las copias y se vuelve a cifrar con la clave nueva. QR y TOTP sin dependencias. Migración 002. Auditoría `mfa_enrolled`, `mfa_failed`, `mfa_recovery_used`, `mfa_recovery_regenerated`, `mfa_disabled` y `mfa_reset_by_admin`.
- **Visor de texto y Markdown:** los archivos de texto se abren en el navegador con doble clic, sin descargarlos (`/view/…`). El Markdown se ve con formato, un índice y la opción de ver su código; el texto y el código, con números de línea, ajuste de líneas, copiar todo y, en los `.log`, avisos y errores en color. Los diagramas `mermaid` se dibujan con Mermaid 12.3.0 en un marco aislado por documento (origen opaco, sin la sesión), copiado con `tools/vendor.py` (versión fija y huella comprobada, sin npm). Se pasa al anterior o al siguiente de la carpeta. Nueva página *Sistema → Vista previa* (`preview.*`): activar o no el visor y los diagramas, el tamaño máximo (2 MB por defecto, hasta 20), la lista entera de extensiones que se abren y las que nunca (de serie, las de secretos y claves: `env`, `pem`, `key`, `ppk`, `asc`; `.env` cuenta como `env`) (con *Restablecer*, que antes de aplicar dice qué se añade y qué se quita). Seguro por construcción: el Markdown se convierte en el servidor sin dependencias (`core/markdown.py`), con todo el texto escapado, sin `javascript:` en los enlaces ni imágenes de otras webs; el HTML y el SVG se ven como código. Hasta 2 MB; lo binario, lo más grande o lo que no está en la lista se descarga. Cuenta en la auditoría como descarga con detalle `view`.
- **Windows como servidor:** `storageweb service install|remove|start|stop|status` lo registra como servicio de Windows (arranque automático, se reinicia si cae) con una cuenta virtual propia, `NT SERVICE\StorageWeb`, que solo tiene acceso a las carpetas que necesita. Sin dependencias nuevas: la API de servicios se usa con `ctypes`. Registro en `<data_dir>/logs/service.log`. Decisión 0019.
- **Plantilla de Caddy** (`packaging/caddy/Caddyfile`, en los paquetes como `/usr/share/storageweb/Caddyfile`), con las opciones del certificado para una red interna. Caddy es la forma recomendada de tener HTTPS en Windows, donde IIS no sirve. Nueva guía *Windows* en la documentación: Python, servicio, Caddy, firewall y certificado.
- **Docker con HTTPS:** `packaging/docker/compose.caddy.yaml` pone Caddy delante (lo más sencillo: el `Caddyfile` va dentro del fichero y no necesita el socket de Docker) y `packaging/docker/compose.traefik.yaml`, Traefik; los dos con HTTPS de Let's Encrypt y StorageWeb sin puerto publicado. Se usan sin el código, con la imagen publicada (`ghcr.io/vsc55/storageweb`, que ya figura en todos los ejemplos en vez de `OWNER`). El de Traefik incluye lo que StorageWeb necesita de Traefik 3: sin el límite de 60 s de lectura (subidas grandes por la unidad de red), nombres con `%`, `?`, `#` o `;`, y quitar la `X-Forwarded-Prefix` del cliente. La página *Red y HTTPS* genera las etiquetas con el nombre y la subruta, y la guía de Docker explica cada opción y cuándo usar cada uno.

### Cambiado

- **La auditoría dice con qué token** se hizo cada acción con archivos: el detalle termina en `token=<nombre>`. Así se distingue un cambio desde VS Code («Visual Studio Code (equipo)»), desde la unidad de red de un equipo o desde un script. Vale para WebDAV, la API de archivos y las subidas por partes.
- ***Mi perfil* por secciones**, con el mismo menú lateral que la administración: *Cuenta* (`/profile`), *Seguridad* (contraseña, verificación en dos pasos y sesiones, `/profile/security`), *Tokens de API* (`/profile/tokens`), *Unidad de red* (`/profile/drive`) y *Espacio* (`/profile/space`); las que el administrador ha desactivado no aparecen. Cada ajuste es una fila con su acción a la derecha y el formulario se despliega debajo, en vez de tarjetas de alturas distintas con huecos.

### Corregido

- En *Mi perfil*, el espacio de la carpeta personal ya no desaparece cuando la unidad de red está desactivada.
- En las páginas más altas que la ventana, la barra lateral ya no se corta al bajar: su color sigue hasta el final.

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

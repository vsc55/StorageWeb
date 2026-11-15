# Registro de cambios

Todos los cambios relevantes del proyecto. Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). El proyecto sigue [versionado semántico](https://semver.org/lang/es/).

Secciones de cada versión: *Añadido*, *Cambiado*, *Obsoleto*, *Eliminado*, *Corregido*, *Seguridad*. También, cuando proceda, *Cambios incompatibles* y *Notas de actualización*.

## [Sin publicar]

### Añadido

- **Internacionalización:**
  - interfaz web y CLI en español e inglés, con selector ES/EN y preferencia guardada por usuario;
  - negociación por `Accept-Language` y opción `default_locale` (por defecto, `en`);
  - fechas y tamaños según el idioma;
  - catálogos gettext comprobados en el CI.
- Opción `--locale` en `user-set`, y variable `STORAGEWEB_LANG` para la CLI.
- **Sesiones en el servidor**: *Personas → Sesiones y tokens* muestra quién está conectado y todos los tokens de API, con cerrar una sesión, todas las de un usuario, las seleccionadas, las inactivas desde hace más de un tiempo o todas menos la propia; *Mi perfil* muestra las propias. Desactivar un usuario o cambiar su contraseña cierra sus sesiones. Comando `sessions-close`.
- **Tokens de API personales** (`Authorization: Bearer sw_…`) con alcance de lectura o de lectura y escritura, caducidad y revocación; el listado de carpetas responde en JSON a los scripts.
- **Bloqueo de IPs**: automático por infracciones (contraseñas erróneas, CSRF, tokens no válidos), manual por IP o red y lista blanca, en *Seguridad → Reglas de bloqueo* e *IPs bloqueadas*. Comandos de rescate `ip-list`, `ip-unban` e `ip-allow`.
- *Sistema → Mantenimiento* y *Copias y base de datos*: retención de la auditoría, compactación de la base de datos, **copias de seguridad desde la web** (crear, descargar, borrar) y copia automática periódica.
- Exportación de la auditoría a **CSV**.
- **Marca**: logo propio (PNG, JPEG, WebP o SVG) y color principal.
- **Caducidad del secreto de Entra ID** con aviso a los admins desde 30 días antes y botón **Renovar secreto**.
- **Nombres de los grupos de Entra ID** en lugar de Object IDs (permiso `Group.Read.All`, concedido al registrar o con *Conceder lectura de grupos*) y buscador por nombre al dar de alta un grupo.
- **Nombre público (FQDN)** (`network.public_url`, también desde la web; basta con `files.empresa.es`, se asume HTTPS) para las URLs externas detrás de un proxy inverso: la de vuelta de Entra ID y la de salida. Variable `STORAGEWEB_PUBLIC_URL` en Docker.
- **Proxies encadenados y subrutas**: `server.proxy_hops` y soporte de `X-Forwarded-Prefix` (`STORAGEWEB_PROXY_HOPS` en Docker).
- Sección **Red y HTTPS** en los ajustes: diagnóstico de cómo llega la petición (esquema, host, subruta, IP real, cabeceras `X-Forwarded-*`) con avisos de los errores típicos, y ejemplos de nginx y Caddy con los valores de la instalación.
- **Nueva página de ajustes**: una sección por tema con su propia dirección, barra de guardar que solo aparece con cambios y aviso al salir sin guardar, errores junto al campo, etiqueta **web** en los valores que mandan sobre `config.json` con *Restablecer* campo a campo, y comprobación de que las carpetas compartidas existen en el servidor.
- **Inicio de sesión** como tarjetas con interruptor (local, PAM, Entra ID), mapeo de roles por filas y **Probar conexión con Entra ID** (tenant, aplicación, Redirect URI y secreto, sin iniciar sesión).
- **Registrar en Entra ID** con un botón: inicio de sesión con código de dispositivo y creación por Microsoft Graph de la aplicación (Redirect URI, permisos de inicio de sesión con consentimiento de administrador, secreto, aplicación empresarial y, opcionalmente, App Roles, claim de grupos y asignación requerida). Los datos se guardan solos y se pasa a comprobar y activar.
- **Asistente de Entra ID** en cuatro pasos: registro, identificadores, usuarios y roles, comprobación y activación.
- **Administración de usuarios** con dos vistas para probar (lista con filtros, paginación y acciones en bloque; paneles con pestañas) y una ficha por secciones con el **acceso efectivo** del usuario y su actividad reciente.
- **Gestión de grupos** (*Personas → Grupos*): grupos locales, de Entra ID (Object ID o App Role) y del sistema, con nombre legible, miembros manuales y sincronizados, grupo de serie **Administradores** (no se puede borrar; sus miembros son los usuarios con rol admin), grupos detectados sin dar de alta, dos vistas para probar (lista y paneles) y la matriz de accesos grupos × carpetas en *Acceso*.
- Acceso de solo lectura por grupo y por usuario en las carpetas compartidas: `storage.shares[].read_only_groups` y `read_only_users` (también `"*"` para que todos lean). Se puede escribir si alguna de las vías por las que entra el usuario lo permite.
- **Administración por zonas**: la barra lateral tiene el **Resumen** y las zonas *Personas*, *Acceso*, *Seguridad* y *Sistema*, cada una con su submenú. Cada página indica si es de configuración (se aplica al guardar), de operación (se aplica al momento) o de solo lectura. *Seguridad* separa las reglas de bloqueo de las IPs bloqueadas, y *Sistema* separa el mantenimiento de las copias y la base de datos.
- **Resumen** de la administración: avisos con su acción (secreto de Entra ID que caduca, carpetas que no existen, copias automáticas que no se hacen, problemas de red), con un contador en la barra lateral; una tarjeta por zona, tareas frecuentes y actividad reciente.
- **Buscador** (Ctrl+K o `/`): páginas, ajustes (lleva al campo exacto y lo resalta), acciones, usuarios, grupos y carpetas, sin distinguir tildes. Sin JavaScript, página de resultados en `/admin/search`.
- *Acceso → Carpetas compartidas*: cada carpeta con quién entra (todos, usuarios y grupos) y con qué permiso, ficha para editarla, crearla o quitarla (los archivos se quedan) y auditoría `share_created`, `share_updated` y `share_deleted`.
- **Almacenamiento externo**: las carpetas compartidas y las personales pueden estar en **S3** (Amazon, MinIO, Wasabi, Backblaze B2, Cloudflare R2, Google Cloud Storage…), en un recurso **SMB** (Windows, Samba, NAS), en un servidor **SFTP**, **WebDAV** (Nextcloud, ownCloud, SharePoint, NAS) o **FTP/FTPS**, o en **Azure Blob Storage**, sin montarlos, además del disco del servidor y los montajes NFS/SMB/rclone. Ubicaciones con nombre (`storage.locations`) en *Sistema → Almacenamiento externo*, con prueba de conexión y secretos ocultos; `storage.shares[].location` y `storage.home_location`. Subidas por partes y descargas con `Range` también en remoto. Extras `storageweb[s3]`, `[smb]`, `[sftp]` y `[azure]`, incluidos en la imagen Docker (FTP y WebDAV no necesitan ninguno). Guía en *Administración → Almacenamiento externo* (ADR 0014).
- **Unidad de red (WebDAV)** en `/dav/`: las carpetas del usuario (personal y compartidas, en cualquier almacenamiento) como unidad en Windows, macOS y Linux, o con rclone, Cyberduck o WinSCP (`rclone bisync` para sincronizar una carpeta del equipo). Usuario y token de API como contraseña (o la contraseña de la cuenta si se activa `security.webdav_passwords`); mismos permisos que la web y sobrescribir exige además el de borrar. La dirección está en *Mi perfil → Unidad de red*. Guía en *Uso → Unidad de red*.
- **Extensión de Visual Studio Code** (`clients/vscode`): sincroniza la carpeta del espacio de trabajo con una carpeta de StorageWeb en los dos sentidos (al guardar y periódicamente), con conflictos guardados como copia y comparables, borrados a la papelera y confirmación de borrados masivos. Panel propio en la barra lateral con **varios servidores** para navegar por sus carpetas, abrir y guardar archivos directamente en el servidor (`storageweb://`), subir, descargar, renombrar, borrar, añadir una carpeta del servidor al espacio de trabajo y elegir qué sincronizar. Para entrar, **iniciar sesión en el navegador** (también con Microsoft) o usuario y token. Pausar y reanudar, exclusiones con `.storagewebignore` y el `.gitignore` de la carpeta, y protección contra el bucle de sincronizar una carpeta que contiene la copia del servidor. JavaScript sin dependencias; `python tools/build_vsix.py` genera el `.vsix` (con `--install` lo instala en VS Code; la tarea de VS Code pregunta si hacerlo), que la CI deja como artefacto y la release adjunta con la versión de StorageWeb. Guía en *Uso → Extensión de VS Code*.
- **Conectar aplicaciones iniciando sesión en el navegador** (`/connect/<aplicación>`, por ahora la extensión de VS Code): el usuario entra en la web (también con Entra ID), acepta y la aplicación recibe un token para ese equipo, sin copiarlo. OAuth con PKCE: código de un solo uso de 5 minutos que solo se canjea con el secreto de la aplicación, vuelta fijada a `vscode://…`, auditoría `app_authorized`.
- **Entrar directamente con Microsoft** (`auth.entra.auto_login`): `/login` va directo a Entra ID (en equipos unidos a Entra ID, sin escribir nada); `/login?manual=1` sigue mostrando la página.
- *Probar conexión* de Entra ID revisa **todos los permisos de la API**: cada permiso de aplicación (concedido y funcionando), los que sobran (aviso de mínimo privilegio) y los de inicio de sesión (`openid`, `profile`, `email`, `User.Read`…), según lo que concedió Microsoft en el último inicio de sesión. Los que falten se pueden arreglar con *Reparar automáticamente*.
- **Reparar automáticamente** la aplicación de Entra ID: si *Probar conexión* encuentra algo arreglable (Redirect URI sin registrar, secreto inválido o caducado, sin lectura de grupos), un botón inicia sesión con Microsoft y StorageWeb añade la Redirect URI, los permisos de Graph con consentimiento de administrador, la aplicación empresarial y, si hace falta, un secreto nuevo. Sustituye a *Conceder lectura de grupos*; también está siempre a mano como *Reparar permisos* en la cabecera de la tarjeta. Junto a él, *Abrir en Entra ID* lleva a la aplicación en el Centro de administración de Entra. Las acciones de la tarjeta van en una fila propia (la cabecera ya no se parte) y la etiqueta *modificado* de los métodos de inicio de sesión ya no sale estirada. Auditoría `entra_app_repaired`.
- Ajustes de Entra ID: la tabla de asociaciones grupo → rol, los grupos permitidos y el asistente muestran el **nombre de cada grupo** junto a su Object ID y permiten **buscar los grupos por nombre** (con el permiso `Group.Read.All`; sin él, se escriben los IDs como antes).
- Asistente de Entra ID: un secreto recién creado (al registrar la aplicación, renovarlo o pegarlo) que Microsoft todavía no acepta aparece como «activándose», no como erróneo, y el paso 4 lo vuelve a comprobar solo durante unos minutos.
- Corregido: *Registrar en Entra ID* fallaba con Python 3.14 al dar el consentimiento (las consultas de Graph llevaban espacios sin codificar) y la página daba un error 500. Ahora las URLs de Graph se codifican siempre, los fallos de conexión se muestran como aviso y, si algo falla después de crear la aplicación, el mensaje dice cuál quedó creada.
- **Rotar tokens de API** en *Mi perfil*: secreto nuevo con el mismo nombre, alcance y caducidad (desde hoy) y el anterior deja de valer en el acto (auditoría `api_token_rotated`). Solo el dueño; el administrador sigue pudiendo revocar.
- El **árbol de carpetas** del explorador funciona como el del Explorador de Windows: en cada nivel del camino se ven todas las carpetas, no solo la abierta (antes, al entrar en una carpeta desaparecían sus hermanas).
- Los mensajes de las acciones (guardar, subir, borrar…) salen como **avisos emergentes abajo a la derecha**, con botón de cerrar; los de confirmación se van solos y los de error se quedan.
- *Seguridad → Auditoría* con **paginación** encima y debajo de la tabla (25, 50, 100, 250 o 500 registros por página, con el total y primera/última; los filtros se mantienen): antes solo se veían las 500 últimas. Las tablas de la administración ya no pierden las esquinas redondeadas.
- **Ocultos para todos** (`storage.hidden`, *Acceso → Carpetas personales*; vale para todas las carpetas): patrones como los de `.gitignore` (`Thumbs.db`, `*.tmp`, `.git/`, `/privado`) de lo que no se lista, no se abre y no se puede crear, en la web, WebDAV y la API. Los archivos siguen en el disco. No es un control de acceso y la lista no se envía a los clientes.
- La unidad de red (WebDAV) lista siempre los archivos que empiezan por punto, aunque la web los oculte (`storage.show_hidden`): un cliente que sincroniza creía que se habían borrado.
- WebDAV con **escritura condicional** (`If-Match`, `If-None-Match`) y `ETag` en las subidas: un cliente no pisa lo que cambió otro.
- Mover y copiar archivos y carpetas en cualquier almacenamiento, también entre carpetas de almacenamientos distintos (`Backend.move`, `copy_between`).
- **Seguridad de rutas en el almacenamiento externo:** todas las rutas se limpian igual en cada tipo (sin `..`, unidades ni caracteres de control), los nombres raros que devuelva un servidor remoto se ocultan y WebDAV rechaza XML con entidades. Batería de ataques en `tests/integration/test_path_security.py`.
- **Extensiones que se registran solas** (ADR 0015): los métodos de inicio de sesión (local, PAM, Entra ID), los tipos de almacenamiento, los avisos del Resumen, las tareas de mantenimiento, los comandos de la CLI y los resultados del buscador se declaran en su propio módulo; añadir uno no toca código general (*Desarrollo → Extender StorageWeb*). Las ubicaciones de almacenamiento aparecen en el buscador. Migración 007: el origen de usuarios y grupos ya no está limitado a `local`, `pam` y `entra`.
- **Activar y desactivar usuarios** de cualquier origen (también Entra ID y PAM) desde la lista y la ficha del usuario, con filtro por estado y auditoría (`user_disabled`, `user_enabled`).
- Página **Mi perfil**: nombre, email, idioma, tema y cambio de contraseña con verificación de la actual.
- Imagen Docker multi-arquitectura (amd64, arm64) publicada en GHCR, con un entrypoint que genera la configuración y crea el admin desde variables o *secrets*.
- Overlay de Gentoo: `www-apps/storageweb` (systemd y OpenRC), `acct-user` y `acct-group`.
- Comandos `backup`, `backup-list` y `restore`: copia consistente de la base de datos, `config.json` y `secret_key`.
- Timer de systemd `storageweb-backup.timer`, instalado desactivado.
- Comando `settings-reset`, vía de rescate para descartar los ajustes web.
- Comando `user-exists` y opción `--password-stdin` en `user-add` y `user-passwd`.
- Endpoint `GET /healthz`.
- Documentación completa en MkDocs, con referencia de configuración, CLI y API generada desde el código y publicada en GitHub Pages.

### Cambiado

- **Nuevo diseño de la interfaz:**
  - barra lateral de iconos (Archivos, Resumen, Personas, Acceso, Seguridad, Sistema y cuenta);
  - explorador en tres columnas: árbol de carpetas, lista y panel de detalle;
  - selección múltiple con barra de acciones y borrado de varios elementos;
  - filtro y orden por nombre, tamaño o fecha;
  - iconos SVG y tema **Sistema / Claro / Oscuro**, guardado por usuario (migración 003);
  - menú de cuenta con perfil, idioma, tema y salir;
  - adaptable a móvil;
  - sin JavaScript, cada fila conserva sus acciones;
  - en modo oscuro, tablas, tarjetas y paneles tienen su propia superficie y bordes con más contraste.
- Estructura de paquete estándar (`src/storageweb`) con capas sin Flask. El comando `storageweb` sustituye a `run.py` y `manage.py`.
- Migraciones de base de datos versionadas (`PRAGMA user_version`).
- La API JSON devuelve todos sus errores en JSON, incluidos los de CSRF.
- `auth.entra.button_label` pasa a estar vacío por defecto: así el botón se muestra traducido. Si lo personalizas, se muestra tal cual.
- Los logs del servidor se escriben en inglés.
- **Configuración por capas**, campo a campo: valores predeterminados < ajustes web < `config.json` < variables de entorno (antes la web ganaba sobre `config.json`).
  - Lo que fijan `config.json` o una variable queda **bloqueado** en la web, con su origen a la vista. El Resumen cuenta cuántos ajustes están bloqueados.
  - *Restablecer* vuelve al **valor predeterminado**. Cada campo modificado lleva la etiqueta **modificado**, el submenú cuenta por página los ajustes que no tienen su valor predeterminado, y *Sistema → Información* los lista con su valor y su origen.
  - Variables `STORAGEWEB_<RUTA>` (con `__` entre niveles) para cualquier ajuste, leídas en cada arranque. Se mantienen los nombres cortos de Docker.
  - **Perfiles de ajustes** (`settings_profile`): varias instancias pueden compartir base de datos con ajustes web distintos.
  - Solo se guarda la diferencia con los valores predeterminados. Auditoría: `settings_updated` indica la sección y hay una acción nueva, `settings_field_reset`.
- **Código reorganizado** sin cambios de comportamiento:
  - proveedores en una carpeta cada uno (`providers/local/`, `pam/`, `entra/`);
  - registro único de los campos de configuración (`settings/fields.py`);
  - ajustes web, administración y CLI partidos en paquetes por tema;
  - los avisos del Resumen, el contador de la barra lateral y el banner salen de un único sitio;
  - CSS y JavaScript repartidos por tema, y cada script solo en las páginas que lo usan.
- Usuarios y grupos se quedan con dos vistas definitivas, *Lista* y *Paneles*.
- Las confirmaciones, avisos y peticiones de texto (borrar, renombrar, descartar cambios…) usan un modal propio con el diseño de la aplicación en lugar de las ventanas del navegador. El botón de confirmar lleva el nombre de la acción y, en las destructivas, el foco empieza en *Cancelar*.
- En los ajustes, los campos cambiados y sin guardar se resaltan, y las pestañas y apartados que los contienen llevan un punto. *Descartar* descarta los cambios pendientes de todas las páginas tras una sola confirmación.
- El `config.json` de los paquetes y el que genera Docker solo traen lo de arranque y la plantilla de las carpetas personales; lo demás se configura en la web.
- En la ficha de usuario, los grupos se gestionan como fichas (añadir y quitar) en lugar de un campo de texto. `--groups` de `user-add` y `user-set` asigna grupos manuales y crea como locales los que no existan.

### Notas de actualización

- `run.py` y `manage.py` ya no existen. Usa `storageweb serve` y `storageweb <comando>`, o `storageweb-admin`.
- Las bases de datos existentes se adoptan automáticamente como esquema 001, y la migración 002 añade `users.locale`.
- La migración 004 crea los grupos: los de los usuarios locales pasan a ser grupos locales con pertenencia manual, y los de Entra ID y PAM aparecen como *grupos sin dar de alta* hasta que les des nombre. Las carpetas que usaban Object IDs siguen funcionando.
- La migración 006 crea las tablas de sesiones, reglas de IP y tokens de API. Las sesiones abiertas antes de actualizar se registran solas en su siguiente petición.
- La migración 005 crea el grupo de serie `admins`. Si ya tenías un grupo local llamado `admins`, se renombra a `admins-local` con sus miembros, y las carpetas que usaban `admins` pasan a dar acceso a los administradores.
- **El idioma por defecto es el inglés.** Para mantener la interfaz en español, elígelo en *System → General and branding* o pon `"default_locale": "es"` en `config.json`; en el fichero, quedará bloqueado en la web.
- **`config.json` gana sobre la web.** Todo campo de `config.json` queda bloqueado en la web. Si tu fichero viene de una versión anterior y lo trae todo, deja solo lo de arranque (`server`, `data_dir`, `database`, `secret_key`, `session`) y lo que quieras fijar: lo demás vuelve a ser editable desde la web.
- **Docker:** las variables `STORAGEWEB_*` ya no se copian a `config.json`. Se leen en cada arranque y bloquean el ajuste en la web.

### Corregido

- En *Mi perfil*, copiar el token de API recién creado y las confirmaciones (cerrar sesiones, revocar tokens) no funcionaban: la página no cargaba ningún script.
- En el móvil, la barra superior con todas las zonas se desborda: ahora se desliza en horizontal.
- Los grupos asignados a mano a un usuario de Entra ID o PAM ya no se pierden en su siguiente inicio de sesión.

## [1.0.0] - 2026-11-11

### Añadido

- Servidor web de archivos (Flask + Waitress): explorador, subida por partes reanudable, descarga con `Range`, carpetas, renombrar y eliminar.
- Inicio de sesión con usuarios locales, PAM y Microsoft Entra ID (OAuth2/OIDC propio o MSAL).
- Roles `admin`/`user`, permisos configurables, panel de administración (usuarios, ajustes, auditoría).
- Carpeta personal y carpetas compartidas por usuario o grupo, también de solo lectura.
- Paquetes `.deb` y `.rpm` con dependencias incluidas, instalador para Ubuntu y CI/CD en GitHub Actions.

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
- Imagen Docker multi-arquitectura (amd64, arm64) publicada en GHCR, con un entrypoint que genera la configuración y crea el admin desde variables o *secrets*.
- Overlay de Gentoo: `www-apps/storageweb` (systemd y OpenRC), `acct-user` y `acct-group`.
- Comandos `backup`, `backup-list` y `restore`: copia consistente de la base de datos, `config.json` y `secret_key`.
- Timer de systemd `storageweb-backup.timer`, instalado desactivado.
- Comando `settings-reset`, vía de rescate para descartar los ajustes web.
- Comando `user-exists` y opción `--password-stdin` en `user-add` y `user-passwd`.
- Endpoint `GET /healthz`.
- Documentación completa en MkDocs, con referencia de configuración, CLI y API generada desde el código y publicada en GitHub Pages.

### Cambiado

- Estructura de paquete estándar (`src/storageweb`) con capas sin Flask. El comando `storageweb` sustituye a `run.py` y `manage.py`.
- Migraciones de base de datos versionadas (`PRAGMA user_version`).
- La API JSON devuelve todos sus errores en JSON, incluidos los de CSRF.
- `auth.entra.button_label` pasa a estar vacío por defecto: así el botón se muestra traducido. Si lo personalizas, se muestra tal cual.
- Los logs del servidor se escriben en inglés.

### Notas de actualización

- `run.py` y `manage.py` ya no existen. Usa `storageweb serve` y `storageweb <comando>`, o `storageweb-admin`.
- Las bases de datos existentes se adoptan automáticamente como esquema 001, y la migración 002 añade `users.locale`.
- **El idioma por defecto es el inglés.** Para mantener la interfaz en español, pon `"default_locale": "es"` en `config.json` o en *Administration → Settings*.

## [1.0.0] - 2026-11-11

### Añadido

- Servidor web de archivos (Flask + Waitress): explorador, subida por partes reanudable, descarga con `Range`, carpetas, renombrar y eliminar.
- Inicio de sesión con usuarios locales, PAM y Microsoft Entra ID (OAuth2/OIDC propio o MSAL).
- Roles `admin`/`user`, permisos configurables, panel de administración (usuarios, ajustes, auditoría).
- Carpeta personal y carpetas compartidas por usuario o grupo, también de solo lectura.
- Paquetes `.deb` y `.rpm` con dependencias incluidas, instalador para Ubuntu y CI/CD en GitHub Actions.

# StorageWeb

Servidor web en Python para subir y descargar archivos. Funciona en Linux, Windows y macOS y está pensado para desplegarse en **Ubuntu** como servicio `systemd`.

- **Inicio de sesión:** usuarios locales (SQLite), usuarios del sistema (PAM, opcional) y **Microsoft Entra ID** (SSO por OAuth2/OIDC propio o por MSAL).
- **Roles:**
  - `admin`: gestiona usuarios y ajustes desde la web y tiene todos los permisos sobre archivos.
  - `user`: trabaja con archivos según los permisos que configure el admin. Por defecto puede subir, descargar y crear carpetas.
- **Almacenamiento:** cada usuario tiene su **home** y además ve las **carpetas compartidas** que le corresponden por usuario o grupo (pueden ser de solo lectura).
- **Configuración:** `config.json` para el arranque y **ajustes editables desde la web** (guardados en SQLite) para el resto.
- **Auditoría:** se registran inicios de sesión, subidas, descargas, borrados, cambios de usuarios y cambios de ajustes.

## Estructura del proyecto

```
src/                      Código Python (paquete "src")
  app.py                  create_app(): ensambla la aplicación
  config/                 defaults.py · loader.py (config.json + validación) · settings.py (ajustes web)
  db/                     schema.sql · conexión y migraciones · users.py · audit.py · settings.py
  providers/              Autenticación: local.py · pam.py · oauth2.py · msal_provider.py (base.SSOProvider)
  core/                   Lógica de negocio: security · storage · permissions · accounts
  routes/                 Capa HTTP (Flask): auth · files · admin · guards (CSRF, sesión, roles)
web/                      Frontend
  templates/              Jinja2 (admin/ para el panel de administración)
  static/css · static/js
config/                   config.example.json (producción) · config.dev.json (desarrollo)
tests/                    pytest
deploy/                   install.sh · postinstall.sh · storageweb.service · nginx · storageweb-admin
packaging/                build.sh + nfpm.yaml (zip, .deb, .rpm)
.github/workflows/        ci.yml (tests en Linux/Windows/macOS) · release.yml (tag vX.Y.Z → release)
run.py                    Arranque (Waitress; --dev = servidor con recarga automática)
manage.py                 CLI de administración
```

Las dependencias van en un solo sentido: `routes → core → db/providers → config`. Para añadir un proveedor SSO basta con crear una subclase de `SSOProvider` en `providers/` y registrarla en `providers/__init__.py`.

## Instalación en Ubuntu

### Opción A: paquete `.deb` (recomendado)

Descarga el `.deb` de la [release](../../releases) e instálalo:

```bash
sudo apt install ./storageweb_X.Y.Z_amd64.deb
sudo storageweb-admin user-add admin --role admin
```

El paquete incluye las dependencias Python como *wheels*, así que **se instala sin conexión a Internet**. Para RHEL, Rocky, Alma o Fedora usa el `.rpm`: `sudo dnf install ./storageweb-X.Y.Z.x86_64.rpm`.

### Opción B: desde el código fuente

```bash
sudo ./deploy/install.sh --nginx          # añade --pam para permitir usuarios del sistema
sudo storageweb-admin user-add admin --role admin
```

Para usar otro usuario de servicio u otras rutas: `sudo APP_USER=svc-files STORAGE_DIR=/datos/files ./deploy/install.sh`.

### Qué se instala

| Qué | Dónde |
|---|---|
| Aplicación + venv | `/opt/storageweb` (propiedad de root, solo lectura para el servicio) |
| Configuración de arranque | `/etc/storageweb/config.json` (`root:storageweb 0640`) |
| BD SQLite (usuarios, ajustes web, auditoría) y secret_key | `/var/lib/storageweb` |
| Archivos | `/srv/storageweb/homes/<usuario>`, `/srv/storageweb/shared`, `/srv/storageweb/public` |
| Servicio | `storageweb.service` en `127.0.0.1:8080`, con el usuario `storageweb` |
| CLI | `sudo storageweb-admin …` |

HTTPS con nginx (Entra ID lo exige):

```bash
sudo cp /usr/share/doc/storageweb/nginx-storageweb.conf /etc/nginx/sites-available/storageweb   # o deploy/
sudo nano /etc/nginx/sites-available/storageweb      # server_name
sudo ln -s /etc/nginx/sites-available/storageweb /etc/nginx/sites-enabled/
sudo certbot --nginx -d files.midominio.com
```

## Administración web

Entra con un usuario `admin` y abre **Administración**:

- **Usuarios:** crear, editar y eliminar. Puedes cambiar el rol, los grupos, el home personalizado, activar o desactivar la cuenta y restablecer la contraseña de los usuarios locales.
  - También puedes **dar de alta por adelantado usuarios de Entra ID** (origen "Entra ID" y su UPN): se vinculan en su primer inicio de sesión.
  - Hay protecciones: no puedes quitarte el rol de admin ni borrarte a ti mismo, y siempre debe quedar al menos un admin activo.
- **Ajustes:** nombre, plantilla de home, carpetas compartidas, permisos del rol `user`, métodos de login, Entra ID (alta automática, rol por defecto, mapeo de roles) y seguridad.
  - Se aplican al momento, sin reiniciar, y **tienen prioridad sobre `config.json`**.
  - "Restablecer a config.json" descarta los ajustes guardados desde la web.
  - El `client_secret` nunca se muestra. Si dejas el campo vacío, se conserva el actual.
- **Auditoría:** registro filtrable por usuario y acción.

Solo se cambian en `config.json` (y requieren reiniciar) los ajustes de arranque: `server.*`, `data_dir`, `database`, `secret_key` y `session.*`.

## Microsoft Entra ID (SSO)

### Implementaciones disponibles (`auth.entra.provider`)

| `provider` | Descripción |
|---|---|
| `oauth2` (por defecto) | Authorization Code + PKCE implementado con la librería estándar de Python. **No hace descubrimiento por red**: las URLs se calculan a partir del tenant. Solo contacta con Entra al canjear el código durante el login. Con `authorize_url`, `token_url` e `issuer` sirve para cualquier proveedor OIDC (o nubes soberanas). Respeta `HTTPS_PROXY`. |
| `msal` | Librería oficial de Microsoft. Descubre la autoridad por red al iniciar cada login. |

Con `oauth2` el `id_token` se valida comprobando `iss`, `aud`, `azp`, `exp`, `nbf` y `nonce`. La firma no se verifica porque el token llega directamente del endpoint de token por TLS y con autenticación por client_secret, que es lo que permite OIDC Core §3.1.3.7.

### Registro de la aplicación

1. En **Entra admin center → App registrations → New registration**, elige una plataforma **Web** con la Redirect URI `https://files.midominio.com/auth/entra/callback`.
2. En **Certificates & secrets**, crea un *client secret*.
3. (Recomendado) En **App roles**, crea `StorageWeb.Admin` y `StorageWeb.User` y asígnalos en *Enterprise applications → Users and groups*. Si prefieres grupos de seguridad, usa *Token configuration → groups claim*.
4. Rellena *tenant_id*, *client_id*, *client_secret* y *redirect_uri* en **Administración → Ajustes** o en `config.json`.

### Alta de usuarios y roles

| Ajuste | Efecto |
|---|---|
| `auto_provision` | `true`: el usuario se crea en su primer login. `false`: solo entran usuarios dados de alta antes por un admin. |
| `default_role` | Rol de los usuarios nuevos cuando no aplica ningún mapeo (`user` o `admin`). |
| `role_mappings` | Grupo (Object ID) o App Role → rol. Por ejemplo `{"StorageWeb.Admin": "admin"}`. Si coinciden varios, gana `admin`. |
| `sync_role_on_login` | Con mapeos definidos, el rol se recalcula en cada login (Entra manda). Si está desactivado, el rol se asigna solo al crear el usuario y luego lo gestiona el admin. |
| `allowed_groups` | Restringe quién puede entrar (vacío = todo el tenant). |

El nombre de usuario es el UPN (`juan@contoso.com`). Nunca se vincula automáticamente con una cuenta local o PAM que tenga el mismo nombre.

## Permisos

| Permiso | `admin` | `user` (por defecto) |
|---|---|---|
| Subir | ✔ | ✔ |
| Descargar | ✔ | ✔ |
| Crear carpetas | ✔ | ✔ |
| Renombrar | ✔ | ✘ (configurable) |
| Eliminar | ✔ | ✘ (configurable) |

En las carpetas compartidas de solo lectura solo se permite descargar, también a los admins. Las carpetas compartidas se asignan a `users` (`*` = todos) o a `groups`:
- usuarios locales: los grupos que asignes;
- PAM: sus grupos del sistema;
- Entra ID: Object IDs de grupo y nombres de App Role.

## Archivos grandes: subidas y descargas

**Subidas.** Desde el navegador los archivos se suben **por partes de hasta 32 MB**:
- **El tamaño del archivo no tiene límite técnico.** Se puede fijar un máximo en *Ajustes → Tamaño máximo por archivo*, donde 0 = sin límite.
- **Reanudables.** Si se corta la red, el navegador reintenta con espera creciente y continúa desde el último byte recibido. Si se recarga la página y se vuelve a soltar el mismo archivo en la misma carpeta, continúa donde se quedó.
- **Espacio en disco.** Antes de empezar se comprueba que hay espacio suficiente; si no, se devuelve el error 507.
- **Archivos parciales.** Mientras se sube, el archivo es un `.sw-upload-*.part` oculto, y al terminar se renombra de forma atómica. Las subidas abandonadas se borran a las 24 h.
- **Ajustes relacionados:**
  - `server.max_upload_mb` limita cada **petición**: cada parte y la subida clásica sin JavaScript.
  - En nginx, `client_max_body_size` debe ser mayor o igual que ese valor.

**Descargas.** No tienen límite de tamaño:
- Se envían en *streaming* y admiten **`Range`**, así que el navegador o un gestor de descargas puede reanudarlas.
- La plantilla de nginx incluye `proxy_buffering off` y `proxy_max_temp_file_size 0` para que nginx no guarde en temporal (por defecto lo haría hasta 1 GB).

API de subida (JSON, requiere sesión y la cabecera `X-CSRF-Token`):

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/uploads` | `{root, path, name, size}` → `{id, chunk_size}` |
| `GET` | `/api/uploads/<id>` | Estado: `{received, size}` |
| `PUT` | `/api/uploads/<id>?offset=N` | Cuerpo binario con una parte. Si el offset no coincide, devuelve 409 con `received` |
| `POST` | `/api/uploads/<id>/complete` | Termina la subida y renombra al nombre final |
| `DELETE` | `/api/uploads/<id>` | Cancela la subida |

## Desarrollo (VS Code)

1. Ejecuta **Tasks: Run Task → StorageWeb: crear entorno .venv** (crea `.venv` e instala `requirements-dev.txt`).
2. Ejecuta **StorageWeb: crear usuario de pruebas** (pregunta el nombre y el rol, que por defecto es `admin`; la contraseña se pide en el terminal).
3. Lanza el servidor con **Ctrl+Shift+B** (**StorageWeb: servidor de pruebas (auto-reload)**). Queda en http://127.0.0.1:8080 con `config/config.dev.json`, y se **reinicia solo** al modificar archivos `.py`, la configuración o las plantillas. Los datos se guardan en `.dev/`.
4. Para depurar con breakpoints, usa **F5 → Depurar servidor** (sin recarga automática).

Sin VS Code:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\...
python manage.py --config config/config.dev.json user-add admin --role admin
python run.py --dev --config config/config.dev.json
```

## Tests

```bash
python -m pytest -q          # o la tarea "StorageWeb: tests" / el panel Testing de VS Code
```

Cubren la configuración y los ajustes web, la seguridad de rutas y nombres, el login local, los permisos por rol, el panel de administración, el SSO (OAuth2 con el endpoint de token simulado y MSAL simulado), el alta y los roles de Entra, las operaciones con archivos y la CLI.

## Releases (GitHub Actions)

- **CI** (`ci.yml`): tests en Ubuntu, Windows y macOS con Python 3.9–3.14, y validación de scripts y JSON.
- **Release** (`release.yml`): al subir un tag `vX.Y.Z` ejecuta los tests y genera estos ficheros, que adjunta a la release de GitHub:

  | Fichero | Contenido |
  |---|---|
  | `storageweb-X.Y.Z.zip` | Código multiplataforma (Windows, macOS, Linux) |
  | `storageweb_X.Y.Z_amd64.deb`, `_arm64.deb` | Debian/Ubuntu, con wheels incluidos |
  | `storageweb-X.Y.Z.x86_64.rpm`, `.aarch64.rpm` | RHEL/Rocky/Alma/Fedora/openSUSE |
  | `SHA256SUMS` | Sumas de comprobación |

  Antes de publicar, el workflow instala el `.deb` en el runner y comprueba que el servicio arranca. Los tags con sufijo (`v1.2.0-rc1`) se publican como *pre-release*.

```bash
git tag v1.0.0 && git push origin v1.0.0
```

Para generar los paquetes en local (Linux con `nfpm`): `packaging/build.sh 1.0.0 amd64`.

## CLI (`storageweb-admin` / `manage.py`)

```bash
storageweb-admin user-add <usuario> [--role admin|user] [--source local|entra] [--groups a,b] [--home RUTA]
storageweb-admin user-passwd <usuario>
storageweb-admin user-set <usuario> [--role ..] [--groups ..] [--home RUTA|''] [--enable|--disable]
storageweb-admin user-del <usuario>          # no borra sus archivos
storageweb-admin user-list
storageweb-admin audit --limit 100 [--user ana]
storageweb-admin check-config                # avisa si no hay ningún admin
```

## Usar el home real del sistema (`/home/<usuario>`)

1. En los ajustes de PAM, activa "Usar el home del sistema" (o pon `home_template` = `/home/{username}`).
2. Da acceso al servicio: `sudo setfacl -R -m u:storageweb:rwx -m d:u:storageweb:rwx /home/ana`.
3. En `storageweb.service`, cambia `ProtectHome=true` a `false` y añade `/home` a `ReadWritePaths`. Después ejecuta `systemctl daemon-reload && systemctl restart storageweb`.

## Seguridad incluida

- **Peticiones y sesión:** CSRF en todos los POST; cookies `HttpOnly`, `Secure` y `SameSite=Lax`; cabeceras CSP, `X-Frame-Options`, `nosniff` y HSTS.
- **Login:** bloqueo tras varios intentos fallidos y comparación en tiempo constante.
- **Archivos:** nombres saneados; protección frente a rutas transversales y symlinks; subidas atómicas que nunca sobrescriben.
- **Roles:** comprobados en el servidor en cada acción (la interfaz además oculta lo que no está permitido).
- **Servicio:** unidad systemd endurecida (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `UMask=0007`).

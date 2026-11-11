# StorageWeb

Servidor web en Python para subir y descargar archivos. Funciona en Linux, Windows y macOS, y está pensado para desplegarse en **Ubuntu** como servicio `systemd`.

- **Inicio de sesión:** usuarios locales (SQLite), usuarios del sistema (PAM, opcional) y **Microsoft Entra ID (SSO)**.
- **Almacenamiento:** cada usuario tiene su **home** y puede acceder a **rutas compartidas** según usuario o grupo (también hay shares de solo lectura).
- **Operaciones:** listar, subir (varios archivos, arrastrar y soltar, barra de progreso), descargar, crear carpetas, renombrar y borrar.
- **Datos:** `config.json` guarda la configuración y SQLite guarda los usuarios y el registro de auditoría.
- **Servicio:** corre con un usuario dedicado sin privilegios (`storageweb` por defecto) detrás de nginx con HTTPS.

## Estructura

```
run.py                  Arranque (Waitress, servidor WSGI multiplataforma)
manage.py               CLI de administración (usuarios, auditoría, validar config)
config.example.json     Configuración de ejemplo
requirements.txt
src/
  __init__.py           create_app()
  config.py             Carga/validación de config.json
  db.py                 SQLite: usuarios y audit_log
  auth.py               Login local, PAM y Entra ID (MSAL)
  files.py              Explorador de archivos
  security.py           CSRF, rutas seguras, límite de intentos, cabeceras
  templates/  static/
deploy/
  install.sh            Instalador para Ubuntu
  storageweb.service    Unidad systemd (endurecida)
  nginx-storageweb.conf Proxy inverso HTTPS
```

## Instalación en Ubuntu

```bash
git clone <repo> storageweb && cd storageweb
sudo ./deploy/install.sh --nginx          # añade --pam para permitir usuarios del sistema
```

Para usar otro usuario o rutas:

```bash
sudo APP_USER=svc-files STORAGE_DIR=/datos/files ./deploy/install.sh --nginx
```

El instalador hace lo siguiente:

| Qué | Dónde |
|---|---|
| Aplicación + venv | `/opt/storageweb` (propiedad de root, solo lectura para el servicio) |
| Configuración | `/etc/storageweb/config.json` (`root:storageweb 0640`) |
| BD SQLite + secret_key | `/var/lib/storageweb` |
| Archivos de usuarios | `/srv/storageweb/homes/<usuario>`, `/srv/storageweb/shared`, `/srv/storageweb/public` |
| Servicio | `storageweb.service` escuchando en `127.0.0.1:8080` |
| CLI | `sudo storageweb-admin …` (ejecuta `manage.py` como el usuario del servicio) |

Después de instalar:

```bash
sudo nano /etc/nginx/sites-available/storageweb      # cambia server_name
sudo ln -s /etc/nginx/sites-available/storageweb /etc/nginx/sites-enabled/
sudo certbot --nginx -d files.midominio.com
sudo nginx -t && sudo systemctl reload nginx

sudo storageweb-admin user-add ana --name "Ana López" --groups rrhh
sudo storageweb-admin check-config
```

Para actualizar, haz `git pull` y vuelve a lanzar `sudo ./deploy/install.sh`. El script conserva `config.json` y la base de datos.

## Desarrollo / otros sistemas (Windows, macOS)

```bash
python -m venv venv
venv\Scripts\activate          # Windows   |   source venv/bin/activate  (Linux/macOS)
pip install -r requirements.txt
copy config.example.json config.json   # y ajústalo (ver abajo)
python manage.py user-add admin
python run.py
```

Para probar en `http://localhost` pon en `config.json`: `"session": {"cookie_secure": false}`, `"server": {"behind_proxy": false}`, y usa rutas válidas para tu sistema (las relativas se resuelven desde la carpeta del `config.json`). Por ejemplo: `"data_dir": "data"` y `"home_template": "data/homes/{username}"`.

Si no defines `STORAGEWEB_CONFIG` ni `--config`, se usa `/etc/storageweb/config.json` si existe y, si no, `./config.json`.

## Configuración (`config.json`)

| Clave | Descripción |
|---|---|
| `server.host` / `port` | Dirección de escucha. Déjalo en `127.0.0.1` si hay nginx delante. |
| `server.behind_proxy` | `true` hace que se confíe en las cabeceras `X-Forwarded-*` de nginx. |
| `server.max_upload_mb` | Tamaño máximo por envío. Ajusta también `client_max_body_size` en nginx. |
| `secret_key` | Si está vacío, se genera en `data_dir/secret_key`. |
| `session.cookie_secure` | `true` en producción (HTTPS). |
| `storage.home_template` | Ruta del home, por ejemplo `/srv/storageweb/homes/{username}`. |
| `storage.create_home` | Crea el home en el primer acceso. |
| `storage.shares[]` | `name` (en la URL), `label`, `path`, `read_only`, `users` (`["*"]` = todos) y `groups`. |
| `auth.local.enabled` | Usuarios gestionados con `manage.py` (contraseñas con hash scrypt). |
| `auth.pam.*` | Usuarios del SO. `allowed_groups` limita quién entra y `use_system_home` usa `/home/<user>`. |
| `auth.entra.*` | SSO con Entra ID (ver abajo). |
| `security.*` | Bloqueo tras N intentos fallidos por IP o usuario. |

Cada usuario puede tener un home propio que sustituye a la plantilla: `storageweb-admin user-set ana --home /datos/ana`.

**Grupos:** los grupos de un usuario local se asignan con `--groups`. Los de PAM son sus grupos del SO. Los de Entra son los Object ID de los grupos y los nombres de los App Roles del token. Todos se comparan en minúsculas con `shares[].groups`.

## Configurar Microsoft Entra ID (SSO)

1. Ve a **Entra admin center → Identity → Applications → App registrations → New registration**.
   - Nombre: `StorageWeb`. Tipo de cuenta: *Solo este directorio organizativo*.
   - Redirect URI: plataforma **Web**, `https://files.midominio.com/auth/entra/callback`.
2. En **Certificates & secrets → New client secret**, copia el *Value*.
3. En **API permissions**, deja `Microsoft Graph → User.Read` (delegado), que viene por defecto.
4. Para restringir el acceso o dar shares por grupo, elige una de estas dos opciones:
   - **App Roles (recomendado):** crea un rol en *App roles* (p. ej. `StorageWeb.User`) y asígnalo en *Enterprise applications → StorageWeb → Users and groups*.
   - **Grupos:** en *Token configuration → Add groups claim → Security groups*, marca la opción "Groups assigned to the application" para evitar el límite de 200 grupos.
   - Opcional: en *Enterprise applications → StorageWeb → Properties*, pon "Assignment required" a **Sí**.
5. Rellena `config.json`:

```json
"entra": {
  "enabled": true,
  "tenant_id": "<Directory (tenant) ID>",
  "client_id": "<Application (client) ID>",
  "client_secret": "<secret>",
  "redirect_uri": "https://files.midominio.com/auth/entra/callback",
  "allowed_groups": ["StorageWeb.User"]
}
```

6. Aplica los cambios con `sudo systemctl restart storageweb`.

Los usuarios de Entra se crean automáticamente en su primer inicio de sesión, identificados por su `oid`. Su nombre de usuario es el UPN (`juan@contoso.com`), así que su home es `homes/juan@contoso.com`. Si ya existe un usuario local con el mismo nombre, **no** se vinculan automáticamente: se rechaza el acceso para evitar suplantaciones.

## Permisos y modelo de usuarios

El servicio corre siempre como `storageweb` (o el usuario que indiques en `APP_USER`), así que todos los archivos subidos pertenecen a ese usuario. Los usuarios de la web no tienen por qué existir en el SO: el aislamiento entre ellos lo aplica la aplicación, que nunca deja salir de la raíz asignada (se comprueban `..`, rutas absolutas y symlinks).

Si quieres que los usuarios suban a su **home real** (`/home/<user>`) con PAM:

1. Pon `"pam": {"enabled": true, "use_system_home": true}` (o `"home_template": "/home/{username}"`).
2. Da acceso al servicio, por ejemplo con ACL: `sudo setfacl -R -m u:storageweb:rwx -m d:u:storageweb:rwx /home/ana`.
3. En `storageweb.service`, cambia `ProtectHome=true` a `false` y añade `/home` a `ReadWritePaths`. Luego ejecuta `systemctl daemon-reload && systemctl restart storageweb`.

## Administración

```bash
sudo storageweb-admin user-add <usuario> [--name ..] [--email ..] [--groups a,b] [--home RUTA]
sudo storageweb-admin user-passwd <usuario>
sudo storageweb-admin user-set <usuario> [--groups a,b] [--home RUTA|''] [--enable|--disable]
sudo storageweb-admin user-del <usuario>          # no borra sus archivos
sudo storageweb-admin user-list
sudo storageweb-admin audit --limit 100 [--user ana]
sudo storageweb-admin check-config
journalctl -u storageweb -f
```

## Seguridad incluida

- Protección CSRF en todas las peticiones POST, y cookies de sesión `HttpOnly`, `Secure` y `SameSite=Lax`.
- Bloqueo temporal tras varios intentos fallidos, y comparación en tiempo constante aunque el usuario no exista.
- Saneado de nombres de archivo (conserva acentos y bloquea nombres reservados de Windows) y control de rutas transversales y symlinks.
- Subidas atómicas: se escribe en un archivo temporal y luego se renombra. Si el nombre ya existe, no se sobrescribe sino que se añade ` (1)`.
- Cabeceras CSP, `X-Frame-Options`, `nosniff` y HSTS (bajo HTTPS).
- Registro de auditoría en SQLite de inicios de sesión, subidas, descargas, borrados y renombrados.
- La unidad systemd incluye `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp` y `UMask=0007`.

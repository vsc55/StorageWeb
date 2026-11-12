"""Valores por defecto y constantes de configuración."""
from __future__ import annotations

ROLES = ("admin", "user")
PERMISSIONS = ("upload", "download", "mkdir", "rename", "delete")
SSO_PROVIDER_NAMES = ("oauth2", "msal")

# Secciones que se pueden editar desde la web (se guardan en SQLite y prevalecen sobre config.json).
# El resto (server, data_dir, database, secret_key, session) solo se configura en config.json
# porque afectan al arranque.
RUNTIME_SECTIONS = ("app_name", "default_locale", "storage", "permissions", "auth", "security")

# Campos secretos: nunca se muestran en la web; si se guardan vacíos se conserva el valor anterior.
SECRET_FIELDS = (("auth", "entra", "client_secret"),)

DEFAULTS: dict = {
    "app_name": "StorageWeb",
    # Idioma por defecto de la interfaz y de la CLI (en | es)
    "default_locale": "en",
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
        "threads": 8,
        # True si hay un proxy inverso (nginx) delante que envía X-Forwarded-*
        "behind_proxy": True,
        # Tamaño máximo de cada petición HTTP (cada parte de una subida y la subida clásica sin JS)
        "max_upload_mb": 2048,
    },
    # Si se deja vacío se genera y guarda en <data_dir>/secret_key
    "secret_key": "",
    "data_dir": "data",
    # Vacío = <data_dir>/storageweb.db
    "database": "",
    "session": {
        "lifetime_hours": 8,
        # Debe ser True en producción (HTTPS). False solo para pruebas en http://localhost
        "cookie_secure": True,
    },
    "storage": {
        # {username} se sustituye por el nombre de usuario (saneado)
        "home_template": "data/homes/{username}",
        "create_home": True,
        # Crea las carpetas de los shares si no existen (útil en desarrollo)
        "create_shares": False,
        "show_hidden": False,
        # Tamaño máximo por archivo en MB (0 = sin límite). Las subidas se hacen por partes,
        # así que no dependen de server.max_upload_mb (que limita cada petición).
        "max_file_size_mb": 0,
        # [{"name", "label", "path", "read_only", "users": ["*"], "groups": []}]
        "shares": [],
    },
    # Permisos del rol "user" (el rol "admin" los tiene todos)
    "permissions": {
        "user": {"upload": True, "download": True, "mkdir": True, "rename": False, "delete": False},
    },
    "auth": {
        "local": {"enabled": True},
        "pam": {
            # Usuarios del sistema operativo (solo Linux/macOS, requiere python-pam)
            "enabled": False,
            "service": "login",
            # Si no está vacío, solo pueden entrar miembros de estos grupos del SO
            "allowed_groups": [],
            # Miembros de estos grupos del SO obtienen el rol admin
            "admin_groups": [],
            # True = usar el home real del usuario (/home/usuario) en vez de home_template
            "use_system_home": False,
        },
        "entra": {
            "enabled": False,
            # "oauth2": OAuth2/OIDC propio (librería estándar, sin descubrimiento previo)
            # "msal":   librería oficial de Microsoft (descubre la autoridad por red)
            "provider": "oauth2",
            "tenant_id": "",
            "client_id": "",
            "client_secret": "",
            "redirect_uri": "",
            "scopes": ["User.Read"],
            # Vacío = texto traducido por defecto ("Iniciar sesión con Microsoft")
            "button_label": "",
            "username_claim": "preferred_username",
            "strip_domain": False,
            # IDs de grupo o App Roles permitidos (vacío = cualquiera del tenant)
            "allowed_groups": [],
            # --- Alta de usuarios ---
            # True: se crea el usuario automáticamente en su primer login
            # False: solo pueden entrar usuarios dados de alta antes por un admin
            "auto_provision": True,
            # Rol asignado a los usuarios nuevos si no aplica ningún mapeo
            "default_role": "user",
            # Grupo (Object ID) o App Role -> rol. Ej.: {"StorageWeb.Admin": "admin"}
            "role_mappings": {},
            # True: con role_mappings definidos, el rol se recalcula en cada login
            "sync_role_on_login": True,
            "single_logout": False,
            # Solo oauth2: endpoints propios (Entra soberano u otro proveedor OIDC)
            "authorize_url": "",
            "token_url": "",
            "issuer": "",
            "logout_url": "",
            "timeout_seconds": 15,
        },
    },
    "security": {
        "max_login_failures": 5,
        "lockout_minutes": 15,
    },
}


# Descripción de cada opción. Es la fuente de docs/referencia/configuracion.md
# (tools/gen_docs.py); un test comprueba que todas las claves de DEFAULTS están descritas.
DESCRIPTIONS: dict[str, str] = {
    "app_name": "Nombre que se muestra en la cabecera y en el título de las páginas.",
    "default_locale": "Idioma por defecto de la interfaz (`en` o `es`) cuando el usuario no ha elegido uno y el "
                      "navegador no indica ninguno disponible.",
    "server.host": "Dirección en la que escucha el servidor. Con un proxy inverso delante, `127.0.0.1`.",
    "server.port": "Puerto TCP de escucha.",
    "server.threads": "Hilos de Waitress para atender peticiones en paralelo.",
    "server.behind_proxy": "Confiar en las cabeceras `X-Forwarded-*` (IP real, HTTPS, host) de un proxy inverso. "
                           "Actívalo solo si hay un proxy delante.",
    "server.max_upload_mb": "Tamaño máximo de cada petición HTTP: cada parte de una subida y la subida clásica sin "
                            "JavaScript. No limita el tamaño de los archivos (ver `storage.max_file_size_mb`).",
    "secret_key": "Clave para firmar las cookies de sesión. Vacía = se genera y guarda en `<data_dir>/secret_key`.",
    "data_dir": "Carpeta de datos del servicio (base de datos, `secret_key`, copias de seguridad).",
    "database": "Ruta del fichero SQLite. Vacía = `<data_dir>/storageweb.db`.",
    "session.lifetime_hours": "Duración de la sesión iniciada, en horas.",
    "session.cookie_secure": "Enviar la cookie de sesión solo por HTTPS. Debe ser `true` en producción; "
                             "`false` solo para pruebas en `http://localhost`.",
    "storage.home_template": "Ruta de la carpeta personal. Debe contener `{username}`, que se sustituye por el "
                             "nombre de usuario saneado.",
    "storage.create_home": "Crear la carpeta personal en el primer acceso del usuario.",
    "storage.create_shares": "Crear las carpetas compartidas si no existen (útil en desarrollo y Docker).",
    "storage.show_hidden": "Mostrar archivos y carpetas que empiezan por punto.",
    "storage.max_file_size_mb": "Tamaño máximo por archivo en MB; `0` = sin límite.",
    "storage.shares": "Lista de carpetas compartidas (ver los campos de cada elemento abajo).",
    "storage.shares[].name": "Identificador en la URL (`/f/<name>/`): letras, números, `_` y `-`. `home` está reservado.",
    "storage.shares[].label": "Nombre visible. Por defecto, `name`.",
    "storage.shares[].path": "Ruta en el servidor. Relativa = respecto a la carpeta del `config.json`.",
    "storage.shares[].read_only": "Solo lectura: únicamente se permite descargar, también a los administradores.",
    "storage.shares[].users": "Usuarios con acceso; `[\"*\"]` = todos.",
    "storage.shares[].groups": "Grupos con acceso (locales, del sistema, o Object IDs/App Roles de Entra ID).",
    "permissions.user.upload": "El rol `user` puede subir archivos.",
    "permissions.user.download": "El rol `user` puede descargar archivos.",
    "permissions.user.mkdir": "El rol `user` puede crear carpetas.",
    "permissions.user.rename": "El rol `user` puede renombrar archivos y carpetas.",
    "permissions.user.delete": "El rol `user` puede eliminar archivos y carpetas.",
    "auth.local.enabled": "Permitir el inicio de sesión de usuarios locales (guardados en SQLite).",
    "auth.pam.enabled": "Permitir el inicio de sesión de usuarios del sistema operativo mediante PAM (Linux/macOS).",
    "auth.pam.service": "Servicio PAM que se usa para autenticar.",
    "auth.pam.allowed_groups": "Si no está vacío, solo entran los miembros de estos grupos del sistema.",
    "auth.pam.admin_groups": "Los miembros de estos grupos del sistema reciben el rol `admin`.",
    "auth.pam.use_system_home": "Usar el home real del usuario (`/home/<usuario>`) en vez de `storage.home_template`.",
    "auth.entra.enabled": "Activar el inicio de sesión con Microsoft Entra ID.",
    "auth.entra.provider": "Implementación: `oauth2` (propia, sin descubrimiento por red) o `msal` (librería de Microsoft).",
    "auth.entra.tenant_id": "Directory (tenant) ID. También admite `organizations` o `common` (multi-tenant).",
    "auth.entra.client_id": "Application (client) ID del registro de aplicación.",
    "auth.entra.client_secret": "Secreto del registro de aplicación. Nunca se muestra en la web.",
    "auth.entra.redirect_uri": "URL de vuelta registrada en Entra ID, p. ej. `https://files.midominio.com/auth/entra/callback`. "
                               "Vacía = se calcula a partir de la petición.",
    "auth.entra.scopes": "Scopes adicionales a `openid profile email`.",
    "auth.entra.button_label": "Texto del botón de inicio de sesión. Vacío = texto por defecto en el idioma del usuario.",
    "auth.entra.username_claim": "Claim del id_token que se usa como nombre de usuario.",
    "auth.entra.strip_domain": "Quitar el dominio del nombre de usuario (`juan@contoso.com` → `juan`). "
                               "Cuidado con las colisiones con usuarios locales.",
    "auth.entra.allowed_groups": "Grupos (Object ID) o App Roles permitidos; vacío = cualquier usuario del tenant.",
    "auth.entra.auto_provision": "Crear el usuario automáticamente en su primer inicio de sesión. Si es `false`, "
                                 "solo entran los usuarios dados de alta antes por un administrador.",
    "auth.entra.default_role": "Rol de los usuarios nuevos cuando no aplica ningún mapeo (`user` o `admin`).",
    "auth.entra.role_mappings": "Grupo (Object ID) o App Role → rol, p. ej. `{\"StorageWeb.Admin\": \"admin\"}`. "
                                "Si coinciden varios, gana `admin`.",
    "auth.entra.sync_role_on_login": "Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión.",
    "auth.entra.single_logout": "Cerrar también la sesión de Microsoft al salir.",
    "auth.entra.authorize_url": "Solo `oauth2`: endpoint de autorización propio (nubes soberanas u otro proveedor OIDC).",
    "auth.entra.token_url": "Solo `oauth2`: endpoint de token propio.",
    "auth.entra.issuer": "Solo `oauth2`: valor esperado del claim `iss`.",
    "auth.entra.logout_url": "Endpoint de cierre de sesión propio.",
    "auth.entra.timeout_seconds": "Tiempo máximo de espera al endpoint de token, en segundos.",
    "security.max_login_failures": "Intentos fallidos (por IP o por usuario) antes de bloquear temporalmente el login.",
    "security.lockout_minutes": "Duración del bloqueo tras demasiados intentos fallidos, en minutos.",
}

# Campos de cada elemento de storage.shares (lista; no aparecen en DEFAULTS)
SHARE_FIELDS = ("name", "label", "path", "read_only", "users", "groups")

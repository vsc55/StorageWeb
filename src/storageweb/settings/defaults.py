"""Valores por defecto y constantes de configuración."""
from __future__ import annotations

ROLES = ("admin", "user")
PERMISSIONS = ("upload", "download", "mkdir", "rename", "delete")
SSO_PROVIDER_NAMES = ("oauth2", "msal")

# Secciones que se pueden editar desde la web (se guardan en SQLite y prevalecen sobre config.json).
# El resto (server, data_dir, database, secret_key, session) solo se configura en config.json
# porque afectan al arranque.
RUNTIME_SECTIONS = ("app_name", "default_locale", "branding", "network", "storage", "permissions", "auth", "security",
                    "maintenance")

# Campos secretos: nunca se muestran en la web; si se guardan vacíos se conserva el valor anterior.
SECRET_FIELDS = (("auth", "entra", "client_secret"),)
SECRET_PATHS = frozenset(".".join(p) for p in SECRET_FIELDS)

# Diccionarios que se tratan como un único valor al combinar ajustes web y config.json (no campo a
# campo): vaciarlos en la web debe dejarlos vacíos, no heredar las claves del fichero.
LEAF_PATHS = (("auth", "entra", "role_mappings"),)

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
        # Número de proxies encadenados delante (nginx = 1; CDN + nginx = 2)
        "proxy_hops": 1,
        # Tamaño máximo de cada petición HTTP (cada parte de una subida y la subida clásica sin JS)
        "max_upload_mb": 2048,
    },
    # Si se deja vacío se genera y guarda en <data_dir>/secret_key
    "secret_key": "",
    "data_dir": "data",
    # Vacío = <data_dir>/storageweb.db
    "database": "",
    # Juego de ajustes web que usa esta instancia: varias instancias pueden compartir base de datos
    # con ajustes distintos, como si cada una tuviera su config.json
    "settings_profile": "default",
    # Nombre público (FQDN) con el que entran los usuarios: "files.empresa.es" (se asume HTTPS). Se usa
    # para las URLs externas: la de vuelta de Entra ID y la de salida. Vacío = el host de cada petición.
    "network": {
        "public_url": "",
    },
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
        # [{"name", "label", "path", "read_only", "users": ["*"], "read_only_users": [],
        #   "groups": [], "read_only_groups": []}]
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
            # Caducidad del client_secret (ISO 8601); vacía = desconocida. Se avisa 30 días antes.
            "secret_expires": "",
        },
    },
    "security": {
        "max_login_failures": 5,
        "lockout_minutes": 15,
        # Bloqueo de IPs tras muchas infracciones (contraseñas erróneas, CSRF, tokens no válidos)
        "ipban_enabled": True,
        "ipban_threshold": 20,
        "ipban_window_minutes": 10,
        "ipban_minutes": 60,
        # Tokens de API personales (Authorization: Bearer sw_…)
        "api_tokens": True,
    },
    "maintenance": {
        # 0 = conservar toda la auditoría
        "audit_retention_days": 0,
        # 0 = sin copias automáticas desde el servicio (se puede usar el timer de systemd)
        "backup_interval_hours": 0,
        "backup_keep": 7,
    },
    "branding": {
        # Color principal (#rrggbb); vacío = el de serie
        "primary_color": "",
        # Lo pone la subida del logo: logo.png, logo.svg…
        "logo": "",
    },
}


# Descripción de cada opción. Es la fuente de docs/referencia/configuracion.md
# (tools/gen_docs.py); un test comprueba que todas las claves de DEFAULTS están descritas.
# La documentación de cada campo (y su etiqueta, página y sinónimos) está en settings/fields.py

# Campos de cada elemento de storage.shares (lista; no aparecen en DEFAULTS)
SHARE_FIELDS = ("name", "label", "path", "read_only", "users", "read_only_users", "groups",
                "read_only_groups")

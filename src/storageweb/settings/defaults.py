"""Valores por defecto y constantes de configuración."""
from __future__ import annotations

ROLES = ("admin", "user")
PERMISSIONS = ("upload", "download", "mkdir", "rename", "delete")
SSO_PROVIDER_NAMES = ("oauth2", "msal")

# Secciones que se pueden editar desde la web (se guardan en SQLite y prevalecen sobre config.json).
# El resto (server, data_dir, database, secret_key, session) solo se configura en config.json
# porque afectan al arranque.
RUNTIME_SECTIONS = ("app_name", "storage", "permissions", "auth", "security")

# Campos secretos: nunca se muestran en la web; si se guardan vacíos se conserva el valor anterior.
SECRET_FIELDS = (("auth", "entra", "client_secret"),)

DEFAULTS: dict = {
    "app_name": "StorageWeb",
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
            "button_label": "Iniciar sesión con Microsoft",
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

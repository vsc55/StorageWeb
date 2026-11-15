"""Valores por defecto y constantes de configuración."""
from __future__ import annotations

ROLES = ("admin", "user")
PERMISSIONS = ("upload", "download", "mkdir", "rename", "delete")

# Secciones que se pueden editar desde la web (se guardan en SQLite y prevalecen sobre config.json).
# El resto (server, data_dir, database, secret_key, session) solo se configura en config.json
# porque afectan al arranque.
RUNTIME_SECTIONS = ("app_name", "default_locale", "branding", "network", "storage", "permissions", "auth", "security",
                    "maintenance", "metrics")

# Campos secretos: nunca se muestran en la web; si se guardan vacíos se conserva el valor anterior.
# Los de cada método de inicio de sesión los añade su proveedor (settings/auth_methods.py).
SECRET_FIELDS: list[tuple[str, ...]] = [("metrics", "token")]
SECRET_PATHS: set[str] = {"metrics.token"}


def is_secret(path: str) -> bool:
    """``True`` si el campo (ruta con puntos) es un secreto: nunca se muestra."""
    return path in SECRET_PATHS

# Diccionarios que se tratan como un único valor al combinar ajustes web y config.json (no campo a
# campo): vaciarlos en la web debe dejarlos vacíos, no heredar las claves del fichero.
# (Los de los métodos de inicio de sesión, como auth.entra.role_mappings, los añade su proveedor.)
LEAF_PATHS: list[tuple[str, ...]] = [("storage", "group_quotas")]

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
        # Patrones (como .gitignore) de lo que no existe para nadie: ni se lista ni se abre ni se crea
        "hidden": [],
        # Tamaño máximo por archivo en MB (0 = sin límite). Las subidas se hacen por partes,
        # así que no dependen de server.max_upload_mb (que limita cada petición).
        "max_file_size_mb": 0,
        # Cuota por defecto de las carpetas personales en MB (0 = sin cuota). Cada usuario puede tener la suya
        # (users.quota_mb), cada grupo la de sus miembros (group_quotas) y cada carpeta compartida, «quota_mb»
        "home_quota_mb": 0,
        # Cuota de la carpeta personal de los miembros de cada grupo: {"rrhh": 5120}. Si alguien está en varios,
        # la mayor (0 = sin cuota gana); la del propio usuario manda sobre todas
        "group_quotas": {},
        # True: lo que no quepa en la cuota no se puede subir, copiar ni mover (HTTP 507). False: solo avisa
        "quota_enforce": True,
        # [{"name", "label", "path", "read_only", "users": ["*"], "read_only_users": [],
        #   "groups": [], "read_only_groups": []}]
        "shares": [],
        # Almacenamientos externos con nombre; las carpetas los eligen con «location».
        # [{"name", "label", "type", <opciones del tipo>}]: cada tipo (S3, SMB…) declara sus opciones
        # en su backend (core/backends/<tipo>.py, settings/location_types.py)
        "locations": [],
        # Ubicación de las carpetas personales: "" = disco local; si no, el nombre de una ubicación
        # (y home_template es una ruta dentro de ella, p. ej. "homes/{username}")
        "home_location": "",
    },
    # Permisos del rol "user" (el rol "admin" los tiene todos)
    "permissions": {
        "user": {"upload": True, "download": True, "mkdir": True, "rename": False, "delete": False},
    },
    # Un apartado por método de inicio de sesión (local, pam, entra…): sus valores los declara cada
    # proveedor en providers/<método>/ y se añaden aquí al registrarlo (settings/auth_methods.py)
    "auth": {},
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
        # Unidad de red (WebDAV en /dav/): se entra con el usuario y un token de API como contraseña
        "webdav": True,
        # Admitir también la contraseña de la cuenta (usuarios locales y PAM) en WebDAV
        "webdav_passwords": False,
    },
    "maintenance": {
        # 0 = conservar toda la auditoría
        "audit_retention_days": 0,
        # 0 = sin copias automáticas desde el servicio (se puede usar el timer de systemd)
        "backup_interval_hours": 0,
        "backup_keep": 7,
    },
    # Métricas para Prometheus en /metrics: con el token (Authorization: Bearer …) o desde las redes permitidas;
    # sin ninguno de los dos, solo desde el propio servidor
    "metrics": {
        "enabled": False,
        "token": "",
        "allowed_networks": [],
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
SHARE_FIELDS = ("name", "label", "location", "path", "read_only", "quota_mb", "users", "read_only_users", "groups",
                "read_only_groups")

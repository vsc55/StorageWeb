"""Registro de los campos de configuración: un solo sitio por campo.

Cada :class:`Field` dice qué es el campo (``doc``, para la referencia generada), cómo se llama en la
web (``label``, el mismo texto que su formulario), en qué página de la administración se edita
(``page``, una clave de ``web/nav.py``) y con qué otras palabras se busca (``words``, buscador Ctrl+K).

Añadir o cambiar un campo de configuración: ``defaults.py`` (valor), ``loader.py`` (validación), este
registro y la plantilla de su página.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..i18n import _, _l
from .defaults import PERMISSIONS, SECRET_PATHS


@dataclass(frozen=True)
class Field:
    doc: str
    label: object = None
    page: str = ""
    words: str = ""


FIELDS: dict[str, Field] = {
    "app_name": Field(
        doc="Nombre que se muestra en la cabecera y en el título de las páginas.",
        label=_l("Application name"),
        page="general",
        words="nombre aplicación título name title"),
    "default_locale": Field(
        doc=("Idioma por defecto de la interfaz (`en` o `es`) cuando el usuario no ha elegido uno y el navegador no "
         "indica ninguno disponible."),
        label=_l("Default language"),
        page="general",
        words="idioma español inglés language locale"),
    "server.host": Field(doc="Dirección en la que escucha el servidor. Con un proxy inverso delante, `127.0.0.1`."),
    "server.port": Field(doc="Puerto TCP de escucha."),
    "server.threads": Field(doc="Hilos de Waitress para atender peticiones en paralelo."),
    "server.behind_proxy": Field(
        doc=("Confiar en las cabeceras `X-Forwarded-*` (IP real, HTTPS, host) de un proxy inverso. Actívalo solo si "
         "hay un proxy delante.")),
    "server.proxy_hops": Field(
        doc=("Número de proxies inversos encadenados delante del servicio (nginx = `1`; una CDN o un balanceador más"
         " nginx = `2`). Se confía en ese número de valores de `X-Forwarded-*`, incluido `X-Forwarded-Prefix` "
         "para servir bajo una subruta.")),
    "network.public_url": Field(
        doc=("Nombre público (FQDN) por el que entran los usuarios: `files.empresa.es`, con puerto o subruta si hace"
         " falta (`files.empresa.es/archivos`). Se asume HTTPS; escribe `http://` delante solo para pruebas en "
         "local. Se usa para las URLs externas: la de vuelta de Entra ID (si `auth.entra.redirect_uri` está "
         "vacía) y la de salida. Vacío = el host de cada petición. Se puede cambiar desde la web."),
        label=_l("Name users type in the browser"),
        page="network",
        words="fqdn dominio url pública https proxy public domain"),
    "server.max_upload_mb": Field(
        doc=("Tamaño máximo de cada petición HTTP: cada parte de una subida y la subida clásica sin JavaScript. No "
         "limita el tamaño de los archivos (ver `storage.max_file_size_mb`).")),
    "secret_key": Field(
        doc="Clave para firmar las cookies de sesión. Vacía = se genera y guarda en `<data_dir>/secret_key`."),
    "data_dir": Field(doc="Carpeta de datos del servicio (base de datos, `secret_key`, copias de seguridad)."),
    "database": Field(doc="Ruta del fichero SQLite. Vacía = `<data_dir>/storageweb.db`."),
    "settings_profile": Field(
        doc=("Perfil de ajustes web: nombre del juego de ajustes guardados en la base de datos que usa esta "
         "instancia (letras, números, `_` y `-`). Varias instancias pueden compartir base de datos con ajustes "
         "distintos.")),
    "session.lifetime_hours": Field(doc="Duración de la sesión iniciada, en horas."),
    "session.cookie_secure": Field(
        doc=("Enviar la cookie de sesión solo por HTTPS. Debe ser `true` en producción; `false` solo para pruebas en"
         " `http://localhost`.")),
    "storage.home_template": Field(
        doc=("Ruta de la carpeta personal. Debe contener `{username}`, que se sustituye por el nombre de usuario "
         "saneado."),
        label=_l("Personal folder template"),
        page="storage",
        words="home carpeta personal plantilla"),
    "storage.create_home": Field(
        doc="Crear la carpeta personal en el primer acceso del usuario.",
        label=_l("Create the personal folder on first access"),
        page="storage",
        words="home crear"),
    "storage.create_shares": Field(
        doc="Crear las carpetas compartidas si no existen (útil en desarrollo y Docker).",
        label=_l("Create shared folders if they do not exist"),
        page="storage",
        words="compartidas crear shares"),
    "storage.show_hidden": Field(
        doc="Mostrar archivos y carpetas que empiezan por punto.",
        label=_l("Show hidden files"),
        page="storage",
        words="ocultos punto hidden dotfiles"),
    "storage.max_file_size_mb": Field(
        doc="Tamaño máximo por archivo en MB; `0` = sin límite.",
        label=_l("Maximum size per file (MB)"),
        page="storage",
        words="tamaño límite subida upload size limit"),
    "storage.shares": Field(
        doc="Lista de carpetas compartidas (ver los campos de cada elemento abajo).",
        label=_l("Shared folders"),
        page="folders"),
    "storage.shares[].name": Field(
        doc="Identificador en la URL (`/f/<name>/`): letras, números, `_` y `-`. `home` está reservado.",
        page="folders"),
    "storage.shares[].label": Field(doc="Nombre visible. Por defecto, `name`.", page="folders"),
    "storage.shares[].path": Field(
        doc="Ruta en el servidor. Relativa = respecto a la carpeta del `config.json`.",
        page="folders"),
    "storage.shares[].read_only": Field(
        doc="Solo lectura: únicamente se permite descargar, también a los administradores.",
        page="folders"),
    "storage.shares[].users": Field(doc='Usuarios con acceso; `["*"]` = todos.', page="folders"),
    "storage.shares[].read_only_users": Field(
        doc=("Usuarios de `users` que solo pueden leer; `\"*\"` = todos los que entran por `[\"*\"]`. Quien entra "
         "también por un grupo con escritura puede escribir."),
        page="folders"),
    "storage.shares[].groups": Field(
        doc=("Grupos con acceso: identificador de un grupo de *Personas → Grupos*, grupo del sistema, u Object "
         "ID/App Role de Entra ID."),
        page="folders"),
    "storage.shares[].read_only_groups": Field(
        doc=("Grupos de `groups` que solo pueden leer (los edita la matriz de accesos). Quien entra también por otro"
         " grupo o por `users` con escritura puede escribir."),
        page="folders"),
    "permissions.user.upload": Field(doc="El rol `user` puede subir archivos.", page="permissions"),
    "permissions.user.download": Field(doc="El rol `user` puede descargar archivos.", page="permissions"),
    "permissions.user.mkdir": Field(doc="El rol `user` puede crear carpetas.", page="permissions"),
    "permissions.user.rename": Field(doc="El rol `user` puede renombrar archivos y carpetas.", page="permissions"),
    "permissions.user.delete": Field(doc="El rol `user` puede eliminar archivos y carpetas.", page="permissions"),
    "auth.local.enabled": Field(
        doc="Permitir el inicio de sesión de usuarios locales (guardados en SQLite).",
        label=_l("Local users"),
        page="auth",
        words="local contraseña password login"),
    "auth.pam.enabled": Field(
        doc="Permitir el inicio de sesión de usuarios del sistema operativo mediante PAM (Linux/macOS).",
        label=_l("System users (PAM)"),
        page="auth",
        words="pam linux sistema system"),
    "auth.pam.service": Field(doc="Servicio PAM que se usa para autenticar.", label=_l("PAM service"), page="auth"),
    "auth.pam.allowed_groups": Field(
        doc="Si no está vacío, solo entran los miembros de estos grupos del sistema.",
        label=_l("Allowed groups"),
        page="auth",
        words="pam grupos permitidos"),
    "auth.pam.admin_groups": Field(
        doc="Los miembros de estos grupos del sistema reciben el rol `admin`.",
        label=_l("Groups with the administrator role"),
        page="auth",
        words="pam administradores admins"),
    "auth.pam.use_system_home": Field(
        doc="Usar el home real del usuario (`/home/<usuario>`) en vez de `storage.home_template`.",
        label=_l("Use the system home folder (/home/user)"),
        page="auth"),
    "auth.entra.enabled": Field(
        doc="Activar el inicio de sesión con Microsoft Entra ID.",
        label="Microsoft Entra ID",
        page="auth",
        words="entra azure microsoft sso oidc oauth"),
    "auth.entra.provider": Field(
        doc="Implementación: `oauth2` (propia, sin descubrimiento por red) o `msal` (librería de Microsoft).",
        label=_l("Implementation"),
        page="auth"),
    "auth.entra.tenant_id": Field(
        doc="Directory (tenant) ID. También admite `organizations` o `common` (multi-tenant).",
        label="Tenant ID",
        page="auth",
        words="entra tenant inquilino"),
    "auth.entra.client_id": Field(
        doc="Application (client) ID del registro de aplicación.",
        label="Client ID",
        page="auth",
        words="entra aplicación app client"),
    "auth.entra.client_secret": Field(
        doc="Secreto del registro de aplicación. Nunca se muestra en la web.",
        label="Client secret",
        page="auth",
        words="entra secreto secret contraseña"),
    "auth.entra.redirect_uri": Field(
        doc=("URL de vuelta registrada en Entra ID, p. ej. `https://files.midominio.com/auth/entra/callback`. Vacía "
         "= se calcula a partir de la petición."),
        label="Redirect URI",
        page="auth",
        words="entra redirección callback"),
    "auth.entra.scopes": Field(
        doc="Scopes adicionales a `openid profile email`.",
        label=_l("Additional scopes"),
        page="auth"),
    "auth.entra.button_label": Field(
        doc="Texto del botón de inicio de sesión. Vacío = texto por defecto en el idioma del usuario.",
        label=_l("Button text"),
        page="auth",
        words="entra botón button"),
    "auth.entra.username_claim": Field(
        doc="Claim del id_token que se usa como nombre de usuario.",
        label=_l("User name claim"),
        page="auth",
        words="entra claim usuario"),
    "auth.entra.strip_domain": Field(
        doc=("Quitar el dominio del nombre de usuario (`juan@contoso.com` → `juan`). Cuidado con las colisiones con "
         "usuarios locales."),
        label=_l("Remove the domain from the user name (juan@contoso.com → juan)"),
        page="auth"),
    "auth.entra.allowed_groups": Field(
        doc="Grupos (Object ID) o App Roles permitidos; vacío = cualquier usuario del tenant.",
        label=_l("Allowed groups / App Roles"),
        page="auth",
        words="entra grupos permitidos app roles"),
    "auth.entra.auto_provision": Field(
        doc=("Crear el usuario automáticamente en su primer inicio de sesión. Si es `false`, solo entran los "
         "usuarios dados de alta antes por un administrador."),
        label=_l("Create the user automatically on first sign-in"),
        page="auth",
        words="entra alta automática provisioning"),
    "auth.entra.default_role": Field(
        doc="Rol de los usuarios nuevos cuando no aplica ningún mapeo (`user` o `admin`).",
        label=_l("Default role"),
        page="auth",
        words="entra rol role"),
    "auth.entra.role_mappings": Field(
        doc=("Grupo (Object ID) o App Role → rol, p. ej. `{\"StorageWeb.Admin\": \"admin\"}`. Si coinciden varios, gana "
         "`admin`."),
        label=_l("Group / App Role → role mapping"),
        page="auth",
        words="entra rol mapeo administradores mapping"),
    "auth.entra.sync_role_on_login": Field(
        doc="Con `role_mappings` definidos, recalcular el rol en cada inicio de sesión.",
        label=_l("Recalculate the role on every sign-in according to the mapping"),
        page="auth"),
    "auth.entra.single_logout": Field(
        doc="Cerrar también la sesión de Microsoft al salir.",
        label=_l("Also sign out of Microsoft when signing out"),
        page="auth",
        words="entra cerrar sesión logout"),
    "auth.entra.authorize_url": Field(
        doc="Solo `oauth2`: endpoint de autorización propio (nubes soberanas u otro proveedor OIDC).",
        label="Authorize URL",
        page="auth"),
    "auth.entra.token_url": Field(doc="Solo `oauth2`: endpoint de token propio.", label="Token URL", page="auth"),
    "auth.entra.issuer": Field(doc="Solo `oauth2`: valor esperado del claim `iss`.", label="Issuer", page="auth"),
    "auth.entra.logout_url": Field(doc="Endpoint de cierre de sesión propio.", label="Logout URL", page="auth"),
    "auth.entra.timeout_seconds": Field(
        doc="Tiempo máximo de espera al endpoint de token, en segundos.",
        label=_l("Timeout (s)"),
        page="auth"),
    "security.max_login_failures": Field(
        doc="Intentos fallidos (por IP o por usuario) antes de bloquear temporalmente el login.",
        label=_l("Failed attempts before locking"),
        page="security",
        words="intentos fallidos contraseña bloqueo"),
    "security.lockout_minutes": Field(
        doc="Duración del bloqueo tras demasiados intentos fallidos, en minutos.",
        label=_l("Lockout minutes"),
        page="security",
        words="bloqueo minutos lockout"),
    "security.ipban_enabled": Field(
        doc=("Bloquear automáticamente las IPs con muchas infracciones (contraseñas erróneas, CSRF no válido, tokens"
         " de API no válidos). Las direcciones de loopback y las de la lista blanca nunca se bloquean."),
        label=_l("Block addresses with many offenses"),
        page="security",
        words="ip bloqueo automático ban infracciones"),
    "security.ipban_threshold": Field(
        doc="Infracciones que bloquean una IP.",
        label=_l("Offenses"),
        page="security",
        words="ip bloqueo infracciones umbral"),
    "security.ipban_window_minutes": Field(
        doc="Ventana en la que se cuentan las infracciones, en minutos.",
        label=_l("In (minutes)"),
        page="security"),
    "security.ipban_minutes": Field(
        doc="Duración del bloqueo automático, en minutos; `0` = hasta que un admin lo quite.",
        label=_l("Block for (minutes)"),
        page="security",
        words="ip bloqueo duración"),
    "security.api_tokens": Field(
        doc="Permitir tokens de API personales (`Authorization: Bearer sw_…`) para scripts.",
        label=_l("Allow personal API tokens"),
        page="security",
        words="api tokens scripts"),
    "maintenance.audit_retention_days": Field(
        doc="Días que se conserva la auditoría; `0` = siempre. La limpieza se hace una vez al día.",
        label=_l("Keep the audit log (days)"),
        page="maintenance",
        words="auditoría retención días borrar"),
    "maintenance.backup_interval_hours": Field(
        doc=("Cada cuántas horas hace el servicio una copia de seguridad en `<data_dir>/backups`; `0` = nunca "
         "(puedes usar el timer de systemd)."),
        label=_l("Automatic backup every (hours)"),
        page="maintenance",
        words="copia seguridad backup automática horas"),
    "maintenance.backup_keep": Field(
        doc="Copias que se conservan en `<data_dir>/backups`; las más antiguas se borran.",
        label=_l("Backups to keep"),
        page="maintenance",
        words="copias conservar backup retención"),
    "branding.primary_color": Field(
        doc="Color principal de la interfaz (`#rrggbb`). Vacío = el de serie.",
        label=_l("Use my own main color"),
        page="general",
        words="color marca branding"),
    "branding.logo": Field(
        doc="Logo propio: lo rellena la subida desde *Sistema → General y marca* (`logo.png`, `logo.svg`…).",
        label=_l("Logo"),
        page="general",
        words="logo imagen marca branding image"),
    "auth.entra.secret_expires": Field(
        doc=("Fecha de caducidad del `client_secret` (ISO 8601). La rellenan el registro automático y la renovación;"
         " con ella se avisa a los admins 30 días antes."),
        label=_l("The secret expires on"),
        page="auth",
        words="entra secreto caducidad caduca expira expiry"),
}
# Los permisos del rol «user» se llaman como el permiso
for _perm in PERMISSIONS:
    _path = f"permissions.user.{_perm}"
    FIELDS[_path] = Field(doc=FIELDS[_path].doc, page="permissions", words="permiso rol usuario permission role")


def field(path: str) -> Field | None:
    if path in FIELDS:
        return FIELDS[path]
    if path.startswith("storage.shares"):
        return FIELDS["storage.shares"]
    return None


def label(path: str) -> str:
    """Etiqueta del campo en la web; si no tiene, su ruta."""
    if path.startswith("permissions.user."):
        from ..core.permissions import PERMISSION_LABELS  # noqa: PLC0415 (core depende de settings)
        return str(PERMISSION_LABELS.get(path.rsplit(".", 1)[1], path))
    info = field(path)
    return str(info.label) if info and info.label else path


def page_of(path: str) -> str:
    """Página de la administración donde se edita el campo (``system`` si no se edita en la web)."""
    info = field(path)
    return info.page if info and info.page else "system"


def display(path: str, value, limit: int = 120) -> str:
    """Un valor de configuración en texto para mostrarlo (los secretos, ocultos)."""
    if path in SECRET_PATHS:
        return "********" if value else _("empty")
    if isinstance(value, bool):
        return _("on") if value else _("off")
    if value in ("", [], {}, None):
        return _("empty")
    if path == "storage.shares":
        return ", ".join(s["name"] for s in value)
    if isinstance(value, list):
        return ", ".join(map(str, value))[:limit]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value)[:limit]


def form_value(path: str, value):
    """Un valor tal como lo muestra el formulario de su página (para que *Restablecer* lo ponga sin guardar)."""
    if isinstance(value, list):
        return (" " if path == "auth.entra.scopes" else ", ").join(map(str, value))
    if path == "network.public_url":
        return str(value or "").removeprefix("https://")
    if path == "auth.entra.secret_expires":
        return str(value or "")[:10]
    return value

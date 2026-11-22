"""Registro de los campos de configuración: un solo sitio por campo.

Cada :class:`Field` dice qué es el campo (``doc``, para la referencia generada), cómo se llama en la
web (``label``, el mismo texto que su formulario), en qué página de la administración se edita
(``page``, una clave de ``web/nav.py``) y con qué otras palabras se busca (``words``, buscador Ctrl+K).

Añadir o cambiar un campo de configuración: ``defaults.py`` (valor), ``loader.py`` (validación), este
registro y la plantilla de su página. Los de ``auth.<método>`` los declara su proveedor
(``providers/<método>/``; ver ``settings/auth_methods.py``).
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
    form: object = None  # valor → texto del formulario, si no basta con el general (form_value)


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
         "local. Se usa para las URLs externas: la de vuelta de Entra ID (`/auth/entra/callback`, que nunca se "
         "guarda: se calcula siempre de aquí) y la de salida. Vacío = la dirección con la que entra el navegador "
         "(su host y puerto). Se puede cambiar desde la web."),
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
    "storage.allowed_folders": Field(
        doc="Carpetas del disco del servidor que se pueden usar: las carpetas compartidas y personales que están en el "
            "disco (sin ubicación de almacenamiento) tienen que estar dentro de alguna, y el botón *Examinar* de la "
            "administración solo enseña lo que hay en ellas. Rutas absolutas (las relativas, respecto al config.json). "
            "Se compara la ruta real: un enlace simbólico que sale de ellas está fuera. Una carpeta que ya existía "
            "fuera deja de abrirse («no disponible») hasta que se mueva o se añada su carpeta. Vacío = cualquiera, "
            "salvo las rutas de red (`\\\\equipo\\recurso`), que solo valen dentro de una de ellas. "
            "Para que solo lo cambie quien administra el servidor, póngase en el config.json o en una variable de "
            "entorno: así la web no lo puede ampliar.",
        label=_l("Allowed server folders"),
        page="server_folders",
        words="carpetas permitidas servidor disco base raíz límite restringir examinar allowed folders"),
    "storage.create_shares": Field(
        doc="Crear las carpetas compartidas si no existen (útil en desarrollo y Docker).",
        label=_l("Create shared folders if they do not exist"),
        page="files",
        words="compartidas crear shares"),
    "storage.show_hidden": Field(
        doc="Mostrar en la web los archivos y carpetas que empiezan por punto. La unidad de red (WebDAV) los muestra siempre.",
        label=_l("Show hidden files"),
        page="files",
        words="ocultos punto hidden dotfiles"),
    "storage.quota_refresh_minutes": Field(
        doc="Cada cuántos minutos se vuelve a medir **en segundo plano** el uso de una carpeta con cuota (de 1 a "
            "10080). Lo que escribe o borra StorageWeb se cuenta al momento; esto recoge lo que otros cambien "
            "directamente en el almacenamiento (otro programa en el mismo bucket o NAS). Nunca se recorre una carpeta "
            "mientras alguien espera, salvo la primera vez desde que arranca el servicio. Una ubicación marcada como "
            "*No cuenta para la cuota* (`quota_exempt`) deja sin cuota las carpetas que estén en ella.",
        label=_l("Measure the quota usage again every (minutes)"),
        page="quotas",
        words="cuota uso medir recalcular reconciliar minutos remoto"),
    "storage.quota_warn_percent": Field(
        doc="Desde qué porcentaje de la cuota se avisa: la barra pasa a ámbar y el Resumen lo dice (de 50 a 99).",
        label=_l("Warn from (percent of the quota)"),
        page="quotas",
        words="cuota aviso porcentaje llena casi warn percent full"),
    "storage.search_max_results": Field(
        doc="La búsqueda por nombre (web y API) para al llegar a tantos resultados (de 10 a 5000) y lo dice.",
        label=_l("Search: at most (results)"),
        page="files",
        words="buscar búsqueda resultados límite search results limit"),
    "storage.search_seconds": Field(
        doc=("Segundos como mucho que dura una búsqueda por nombre (de 1 a 120); al cumplirlos para y enseña lo que "
             "lleva. En almacenamiento remoto recorrer carpetas es lento: súbelo si hace falta."),
        label=_l("Search: at most (seconds)"),
        page="files",
        words="buscar búsqueda tiempo segundos lenta search time seconds"),
    "storage.search_max_folders": Field(
        doc="Carpetas como mucho que recorre una búsqueda por nombre (de 100 a 1 000 000).",
        label=_l("Search: at most (folders looked at)"),
        page="files",
        words="buscar búsqueda carpetas recorrer límite search folders"),
    "storage.upload_stale_hours": Field(
        doc=("Horas sin actividad tras las que se descarta una subida por partes a medias (de 1 a 720): hasta entonces "
             "se puede reanudar; después se borra su `.part`."),
        label=_l("Discard unfinished uploads after (hours)"),
        page="files",
        words="subida reanudar abandonada parte part limpieza upload resume stale"),
    "storage.page_size": Field(
        doc="Elementos de una carpeta que el explorador muestra de una vez (de 50 a 5000). Las carpetas con más se "
            "ven según `storage.listing_mode`. La API y la unidad de red siempre listan la carpeta entera.",
        label=_l("Items shown at once"),
        page="files",
        words="paginar paginación página miles elementos listado scroll"),
    "storage.listing_mode": Field(
        doc="Cómo se ve una carpeta con más de `storage.page_size` elementos: `scroll` (se cargan más al bajar), "
            "`pages` (por páginas, con *Anterior* y *Siguiente*) o `search` (solo los primeros; el resto, con el "
            "filtro). En los tres, el filtro de la carpeta busca entre todos sus elementos.",
        label=_l("Folders with many items"),
        page="files",
        words="paginar paginación páginas scroll desplazamiento cargar más buscar filtro miles"),
    "storage.hidden": Field(
        doc="Archivos y carpetas **ocultos para todos**: no se listan ni se pueden abrir ni crear, ni en la web ni por "
            "WebDAV ni por la API (la extensión de VS Code tampoco los sincroniza). Patrones como los de `.gitignore`, "
            "sobre la ruta dentro de cada carpeta: `Thumbs.db`, `*.tmp` (en cualquier sitio), `.git/` (solo carpetas), "
            "`/privado` (desde la raíz). Los archivos siguen en el disco. Es para no mostrar cosas (basura del sistema, "
            "carpetas técnicas), no un control de acceso: para eso, los permisos de las carpetas. La lista no se envía a "
            "los clientes.",
        label=_l("Hidden for everyone"),
        page="files",
        words="ocultar ocultos patrones ignorar gitignore excluir hidden"),
    "storage.home_quota_mb": Field(
        doc="Cuota por defecto de las **carpetas personales**, en MB; `0` = sin cuota. Cada usuario puede tener otra "
            "en su ficha, y cada grupo una para sus miembros (`storage.group_quotas`).",
        label=_l("Quota of personal folders (MB)"),
        page="quotas",
        words="cuota espacio limite quota personal"),
    "storage.group_quotas": Field(
        doc="Cuota de la carpeta personal de los miembros de cada grupo, en MB: `{\"rrhh\": 5120}`. Si alguien está en "
            "varios, la mayor (`0` = sin cuota gana). La del propio usuario manda sobre la de sus grupos. Se edita en la "
            "ficha de cada grupo (se guarda en el grupo); la de un grupo puesta aquí en config.json no se puede "
            "cambiar desde la web.",
        label=_l("Personal folder quota of the members (MB)"),
        page="quotas",
        words="cuota grupo miembros quota group"),
    "storage.quota_enforce": Field(
        doc="Si las cuotas **impiden escribir**: lo que no quepa no se puede subir, copiar ni mover (web, API y "
            "unidad de red responden 507). `false` = solo avisan (a partir del 90 % y al superarla).",
        label=_l("Block uploads that do not fit in the quota"),
        page="quotas",
        words="cuota bloquear impedir subir quota enforce block"),
    "storage.max_file_size_mb": Field(
        doc="Tamaño máximo por archivo en MB; `0` = sin límite.",
        label=_l("Maximum size per file (MB)"),
        page="files",
        words="tamaño límite subida upload size limit"),
    "storage.home_location": Field(
        doc=("Ubicación de `storage.locations` donde están las carpetas personales. Vacía = el disco del servidor; "
             "con una ubicación, `home_template` es una ruta dentro de ella (`homes/{username}`)."),
        label=_l("Where personal folders live"),
        page="storage",
        words="ubicación almacenamiento s3 smb nas carpetas personales home"),
    "storage.locations": Field(
        doc="Almacenamientos externos con nombre, que eligen las carpetas (ver *Tipos de ubicación*, abajo). Los "
            "de config.json o del entorno se ven en la web de solo lectura, junto a los creados desde la web (que "
            "se guardan en su propia tabla).",
        label=_l("Storage locations"),
        page="locations",
        words="almacenamiento externo s3 smb nas minio bucket samba windows ubicación"),
    "storage.locations[].name": Field(doc="Identificador: letras, números, `_` y `-`.", page="locations"),
    "storage.locations[].label": Field(doc="Nombre visible. Por defecto, `name`.", page="locations"),
    "storage.locations[].type": Field(doc="Tipo de almacenamiento; sus opciones, en la tabla de su tipo (abajo).",
                                      page="locations"),
    "storage.shares": Field(
        doc="Lista de carpetas compartidas (ver los campos de cada elemento abajo). Las de config.json o del "
            "entorno se ven en la web de solo lectura, junto a las creadas desde la web (que se guardan en su propia "
            "tabla); si un nombre está en los dos sitios, manda config.json.",
        label=_l("Shared folders"),
        page="folders"),
    "storage.shares[].name": Field(
        doc="Identificador en la URL (`/f/<name>/`): letras, números, `_` y `-`. `home` está reservado.",
        page="folders"),
    "storage.shares[].label": Field(doc="Nombre visible. Por defecto, `name`.", page="folders"),
    "storage.shares[].location": Field(
        doc=("Ubicación de `storage.locations` donde está la carpeta (S3, SMB). Vacía = el disco del servidor "
             "(también lo montado en él: NFS, SMB/CIFS…)."),
        page="folders"),
    "storage.shares[].path": Field(
        doc=("En el disco: ruta en el servidor (relativa = respecto a la carpeta del `config.json`). En una "
             "ubicación: ruta dentro de ella (vacía = su raíz)."),
        page="folders"),
    "storage.shares[].quota_mb": Field(
        doc="Cuota de la carpeta compartida en MB; `0` o ausente = sin cuota. Solo avisa.", page="folders"),
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
    "permissions.user.edit": Field(doc="El rol `user` puede editar archivos de texto en el navegador (desde el visor).",
                                   page="permissions"),
    "permissions.default_role": Field(
        doc=("El rol de las **cuentas nuevas**: las que se dan de alta desde la web o con `storageweb-admin "
             "user-add` sin `--role`, las importadas y las que crea un método de inicio de sesión al entrar si el suyo "
             "(Entra ID: *Rol de los usuarios nuevos*) está vacío. `user`, `admin` o la clave de un rol propio "
             "(*Acceso → Roles*). Las cuentas que ya existen no cambian."),
        label=_l("Role of new accounts"),
        page="permissions",
        words="rol por defecto cuentas nuevas alta usuarios nuevos default role"),
    "permissions.user.share": Field(doc=("El rol `user` puede crear **enlaces para compartir** con gente de fuera "
                                         "(ver `sharing.*`). Apagado de serie."), page="permissions"),
    "sharing.links": Field(
        doc=("Enlaces para compartir un archivo o una carpeta con gente sin cuenta (`/s/<token>`): con caducidad, "
             "contraseña opcional y límite de descargas, o un **buzón** para que suban archivos. Los crea quien tenga "
             "el permiso *Compartir con enlaces* (los administradores siempre). Apagado, ninguno funciona (ni los ya "
             "creados) y no se pueden crear."),
        label=_l("Share links"),
        page="sharing",
        words="enlaces compartir fuera público externo link share anonymous"),
    "sharing.default_days": Field(
        doc="Cuántos días dura un enlace si quien lo crea no elige otra cosa (de `1` a `3650`).",
        label=_l("Days a link lasts by default"),
        page="sharing",
        words="enlaces caducidad días"),
    "sharing.max_days": Field(
        doc=("Lo máximo que puede durar un enlace, en días (de `0` a `3650`); `0` = sin máximo, y entonces se pueden "
             "crear enlaces que no caducan."),
        label=_l("Days a link can last at most"),
        page="sharing",
        words="enlaces caducidad máximo días"),
    "sharing.require_password": Field(
        doc="Exigir contraseña a todos los enlaces nuevos (los ya creados no cambian).",
        label=_l("Require a password for every link"),
        page="sharing",
        words="enlaces contraseña obligatoria"),
    "sharing.keep_days": Field(
        doc=("Días que se conservan los enlaces **quitados o caducados** (siguen en la lista, con los filtros "
             "*Quitados* y *Caducados*) antes de que la limpieza diaria borre su fila; `0` = nunca se borran. Su "
             "historial no se borra con ellos: sigue `sharing.history_days` y se ve en el filtro *Borrados*."),
        label=_l("Keep removed or expired links (days)"),
        page="sharing",
        words="enlaces conservar quitados caducados borrar limpieza días retención"),
    "sharing.history_days": Field(
        doc=("Días que se conserva el **historial** de los enlaces (cada visita, descarga, subida, contraseña "
             "equivocada… con su IP y navegador); `0` = lo mismo que la auditoría (`maintenance.audit_retention_days`). "
             "Con un número, no puede ser menor que `sharing.keep_days`: un enlace no se queda sin su historial."),
        label=_l("Keep the history of the links (days)"),
        page="sharing",
        words="enlaces historial actividad trazabilidad conservar retención días ip navegador"),
    "sharing.upload_links": Field(
        doc=("Permitir **buzones**: enlaces a una carpeta para que alguien de fuera suba archivos sin ver lo que hay "
             "(necesitan además poder subir a esa carpeta)."),
        label=_l("Allow drop boxes (upload links)"),
        page="sharing",
        words="buzón subir enlace recibir archivos upload drop box"),
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
        page="clients",
        words="api tokens scripts"),
    "security.webdav": Field(
        doc=("Unidad de red: servidor WebDAV en `/dav/` (Windows, macOS, Linux, rclone…). Se entra con el nombre "
             "de usuario y un token de API como contraseña. Necesita `api_tokens` salvo que se admita la "
             "contraseña de la cuenta."),
        label=_l("Network drive (WebDAV)"),
        page="clients",
        words="webdav unidad red network drive dav rclone mapear windows finder"),
    "security.api_token_max_days": Field(
        doc=("Días como mucho que puede durar un token de API; `0` = sin límite (se pueden crear sin caducidad). "
             "Con un límite no se pueden crear sin caducidad ni más largos, al rotarlos o conectar una aplicación se "
             "recortan, y los que ya existen dejan de valer al cumplir ese tiempo desde que se crearon."),
        label=_l("Longest API token lifetime (days)"),
        page="clients",
        words="tokens caducidad máximo días política expiry lifetime"),
    "security.api_token_unused_days": Field(
        doc=("Días sin usarse tras los que el Resumen avisa de los tokens de API que siguen valiendo (mejor "
             "revocarlos: si uno se filtra, sigue funcionando). `0` = sin aviso; de 0 a 3650."),
        label=_l("Warn about tokens unused for (days)"),
        page="clients",
        words="tokens sin usar aviso revocar días unused"),
    "security.webdav_passwords": Field(
        doc=("Admitir también la contraseña de la cuenta (usuarios locales y PAM) en WebDAV. Desactivado: solo "
             "tokens, que se pueden revocar y limitar a lectura."),
        label=_l("Also accept the account password in WebDAV"),
        page="clients",
        words="webdav contraseña password"),
    "security.mfa_required": Field(
        doc=("Quién debe tener la **verificación en dos pasos** (TOTP): `off` (nadie, quien quiera la activa en *Mi "
             "perfil*), `admins` (los administradores) o `all` (todas las cuentas). Solo las cuentas con contraseña "
             "(locales y PAM): quien entra con Microsoft Entra ID usa el segundo factor de Microsoft. Quien la debe y "
             "no la tiene la configura al iniciar sesión; quien la tiene la usa siempre, diga lo que diga esto."),
        label=_l("Two-step verification required for"),
        page="auth",
        words="mfa 2fa totp verificación dos pasos segundo factor autenticador authenticator two-step"),
    "security.passkeys": Field(
        doc=("Permitir **passkeys** (WebAuthn: Windows Hello, Touch ID, el móvil o una llave de seguridad) como "
             "segundo paso, además de la app de códigos; cada cuenta puede tener varias. Necesitan que "
             "`network.public_url` tenga un nombre (no una IP) y HTTPS, salvo `localhost`: la passkey queda atada a "
             "ese nombre y no se puede mover a otro. Desactivado, no se ofrecen ni se aceptan (las cuentas que solo "
             "tengan passkeys entran con sus códigos de recuperación)."),
        label=_l("Allow passkeys"),
        page="auth",
        words="passkey passkeys webauthn fido llave seguridad windows hello touch id huella security key"),
    "security.passkey_login": Field(
        doc=("**Entrar solo con una passkey**, sin escribir el usuario ni la contraseña: un botón *Entrar con una "
             "passkey* en la página de inicio de sesión. La passkey tiene que verificar a la persona (PIN, huella o "
             "cara), así que vale por los dos pasos. Solo para las cuentas que guardan aquí su contraseña (las "
             "locales): en las de PAM decide el sistema si la cuenta sigue valiendo, y eso solo se sabe con su "
             "contraseña. Necesita `security.passkeys`. Las passkeys añadidas con esto encendido se guardan en el "
             "dispositivo (*credencial residente*), que es lo que permite elegirlas sin escribir el usuario."),
        label=_l("Sign in with a passkey only, without the password"),
        page="auth",
        words="passkey sin contraseña passwordless entrar login usernameless residente"),
    "security.password_check": Field(
        doc=("Al poner una contraseña (crear una cuenta, cambiarla en *Mi perfil* o un administrador a otra persona), "
             "rechazar las **más comunes**: la lista de unas 19 000 que viaja con StorageWeb o, si se ha descargado o "
             "subido una en *Seguridad → Contraseñas* (o con `storageweb-admin password-list`), la propia del "
             "servidor (`<data_dir>/common_passwords.txt`). No se consulta nada fuera. Las contraseñas que ya existen "
             "no se tocan."),
        label=_l("Reject common passwords"),
        page="passwords",
        words="contraseña común débil filtrada lista password common weak breached blocklist"),
    "security.password_min_distinct": Field(
        doc=("Caracteres distintos que tiene que tener como mínimo una contraseña nueva, de `1` (sin comprobar) a "
             "`20`: `aaaaaaaaaa` o `abababababab` son largas, pero se adivinan enseguida."),
        label=_l("Different characters at least"),
        page="passwords",
        words="contraseña caracteres distintos repetidos password distinct"),
    "security.password_require": Field(
        doc=("Tipos de caracteres que tiene que tener una contraseña nueva: `lower` (minúscula), `upper` "
             "(mayúscula), `digit` (número) y `symbol` (cualquier otro). De serie, ninguno: la longitud protege más "
             "y obligar a mezclar las hace difíciles de recordar más que de adivinar (NIST SP 800-63B)."),
        label=_l("It must contain"),
        page="passwords",
        words="contraseña mayúscula minúscula número símbolo complejidad password complexity uppercase digit"),
    "security.password_reject_username": Field(
        doc="Rechazar las contraseñas que contienen el nombre de usuario (sin distinguir mayúsculas).",
        label=_l("Reject passwords that contain the user name"),
        page="passwords",
        words="contraseña nombre usuario password username"),
    "security.password_blocklist": Field(
        doc=("Palabras propias que una contraseña nueva no puede **contener**, sin distinguir mayúsculas: el nombre "
             "de la empresa, del servicio, la ciudad… De 4 caracteres o más. Se aplica aunque las comunes estén "
             "apagadas."),
        label=_l("Forbidden words"),
        page="passwords",
        words="contraseña palabras prohibidas lista negra empresa password blocklist banned words"),
    "security.password_breach_check": Field(
        doc=("Rechazar las contraseñas que aparecen en **filtraciones conocidas**, preguntando a Pwned Passwords de "
             "Have I Been Pwned (`api.pwnedpasswords.com`) al ponerlas. Solo se envían los 5 primeros caracteres de "
             "su SHA-1 (k-anonimato): ni la contraseña ni su hash completo salen del servidor. **Sale a internet**; "
             "si el servicio no contesta, la contraseña se acepta."),
        label=_l("Reject passwords that appear in known data breaches (Have I Been Pwned)"),
        page="passwords",
        words="contraseña filtrada filtraciones pwned hibp have i been pwned breach leaked"),
    "security.password_list_urls": Field(
        doc=("De dónde se descarga la lista propia de contraseñas comunes (*Descargar ahora* en *Seguridad → "
             "Contraseñas* o `storageweb-admin password-list --download`): direcciones `https://` de ficheros de "
             "texto con una por línea, que se juntan. De serie, las de SecLists de las que sale la lista de serie, en "
             "su versión actual. Solo se guardan las de 10 caracteres o más, en minúsculas, con un tope de 64 MB."),
        label=_l("Download the list from"),
        page="passwords",
        words="contraseñas comunes lista descargar actualizar seclists url password list download"),
    "security.dependency_check_hours": Field(
        doc=("Cada cuántas horas se comprueban solas las bibliotecas instaladas (Python y el JavaScript copiado) "
             "contra OSV.dev (vulnerabilidades conocidas) y PyPI y npm (versiones nuevas), de `0` a `720`; de serie `24` "
             "(una vez al día); `0` = solo con el botón *Comprobar ahora*. **Sale a internet** (`pypi.org`, "
             "`registry.npmjs.org`, `api.osv.dev`): en un servidor sin salida, ponlo a `0`. "
             "El resultado se ve en *Seguridad → Vulnerabilidades* y, si las hay, en el Resumen y en *Estado de la seguridad*. "
             ""),
        label=_l("Check the libraries automatically every (hours)"),
        page="vulnerabilities",
        words="vulnerabilidades cve osv bibliotecas dependencias automático comprobar horas vulnerabilities"),
    "security.password_min_length": Field(
        doc=("Longitud mínima de una contraseña nueva de las cuentas locales, de `10` (nunca menos) a `128`. Se aplica "
             "al ponerla (alta, *Mi perfil*, un administrador o la CLI); las que ya existen no se tocan."),
        label=_l("Minimum password length"),
        page="passwords",
        words="contraseña longitud mínima caracteres largo password length minimum"),
    "preview.enabled": Field(
        doc=("Abrir en el navegador, sin descargarlos, los archivos de texto y Markdown, las imágenes, los PDF, los "
             "vídeos y el audio (doble clic en el explorador; cada tipo multimedia se puede apagar aparte). "
             "Desactivado, todos se descargan como cualquier otro archivo."),
        label=_l("Open files in the browser"),
        page="preview",
        words="visor vista previa ver abrir markdown texto preview viewer"),
    "preview.diagrams": Field(
        doc=("Dibujar los diagramas `mermaid` de los `.md` (con Mermaid, en un marco aislado del resto de la página). "
             "Desactivado, se ve su código y Mermaid no se descarga."),
        label=_l("Draw Mermaid diagrams"),
        page="preview",
        words="diagramas mermaid gráficos diagrams"),
    "preview.highlight": Field(
        doc="Colorear el código (Python, PHP, JavaScript, SQL, YAML, PowerShell… y los bloques de código de los `.md`) "
            "con highlight.js. Desactivado, se ve sin colores y highlight.js no se descarga. Los archivos de más de "
            "1 MB se ven siempre sin colores.",
        label=_l("Color the code"),
        page="preview",
        words="colores sintaxis resaltado highlight código syntax"),
    "preview.images": Field(
        doc=("Ver las imágenes en el visor: `png`, `jpg`, `gif`, `webp`, `bmp`, `ico` y `avif`. El SVG no: puede llevar "
             "código, así que se ve como texto (si `svg` está en las extensiones). Desactivado, se descargan."),
        label=_l("Show images"),
        page="preview",
        words="imágenes fotos png jpg jpeg gif webp images pictures photos"),
    "preview.thumbnails": Field(
        doc=("Miniaturas de las imágenes en el explorador (en la lista y, más grande, en el panel de detalle). Las "
             "genera el servidor con **Pillow**, que es opcional (`pip install storageweb[thumbnails]`; sin él se "
             "ven iconos), y las guarda en `<data_dir>/thumbnails`, nunca en la carpeta de nadie. Solo de las "
             "imágenes que abre el visor (`preview.images`), con el decodificador de su formato y nada más. Ver una "
             "miniatura no cuenta en la auditoría."),
        label=_l("Thumbnails in the file browser"),
        page="preview",
        words="miniaturas thumbnails imágenes vista explorador pillow fotos"),
    "preview.thumbnail_max_mb": Field(
        doc=("La imagen más grande de la que se hace miniatura, en MB (de `1` a `500`): el servidor la lee entera "
             "para reducirla. Más grande, se ve el icono."),
        label=_l("Thumbnails: largest image (MB)"),
        page="preview",
        words="miniaturas tamaño máximo imagen"),
    "preview.thumbnail_cache_mb": Field(
        doc=("Lo que pueden ocupar las miniaturas guardadas, en MB (de `10` a `100000`). Una vez al día se borran las "
             "que nadie ha pedido en 60 días y, si aun así ocupan más, las menos usadas. Cada una ocupa unos 10 KB."),
        label=_l("Thumbnails: space for the cache (MB)"),
        page="preview",
        words="miniaturas caché espacio disco"),
    "preview.pdf": Field(
        doc=("Ver los PDF en el visor, con el visor de PDF del propio navegador (aislado de la página). Desactivado, o "
             "en un navegador sin visor de PDF, se descargan."),
        label=_l("Show PDF documents"),
        page="preview",
        words="pdf documentos documents acrobat"),
    "preview.video": Field(
        doc=("Reproducir los vídeos en el visor: `mp4`, `m4v`, `webm` y `ogv`, con lo que sepa reproducir el navegador; "
             "se piden por partes, así que se puede saltar a cualquier punto. Desactivado, se descargan."),
        label=_l("Play videos"),
        page="preview",
        words="vídeo video películas mp4 webm reproducir play movies"),
    "preview.audio": Field(
        doc=("Reproducir el audio en el visor: `mp3`, `wav`, `ogg`, `oga`, `opus`, `m4a`, `aac`, `flac` y `weba`. "
             "Desactivado, se descargan."),
        label=_l("Play audio"),
        page="preview",
        words="audio música sonido mp3 wav flac reproducir music sound play"),
    "preview.max_mb": Field(
        doc=("Tamaño máximo, en MB, de un archivo de texto para verse en el navegador (de 1 a 20); más grande, se "
             "descarga (un log, por trozos). No se aplica a imágenes, PDF, vídeo ni audio."),
        label=_l("Largest file to view (MB)"),
        page="preview",
        words="tamaño máximo visor size limit"),
    "preview.extensions": Field(
        doc=("Extensiones (sin el punto) que se abren en el visor: la lista entera. De serie, Markdown (`md`…, con "
             "formato), HTML y SVG (`html`, `svg`…, siempre como código), texto y datos (`txt`, `log`, `csv`, `json`, "
             "`yml`…) y código (`py`, `js`, `ps1`, `sh`, `sql`…). Si la cambias, se guarda la tuya entera; "
             "*Restablecer* vuelve a la de serie. Archivos como `README` o `Dockerfile` se abren siempre."),
        label=_l("Extensions that open in the viewer"),
        page="preview",
        words="extensiones texto código markdown abrir extensions"),
    "preview.blocked_extensions": Field(
        doc=("Extensiones que nunca se abren en el visor, aunque estén en la lista anterior: se descargan. De serie, "
             "archivos de texto que suelen guardar secretos o claves: `asc`, `env`, `key`, `pem` y `ppk`. Un archivo "
             "sin extensión que empieza por punto cuenta como si lo fuera: `.env` se bloquea con `env`."),
        label=_l("Never open in the viewer"),
        page="preview",
        words="extensiones bloquear excluir nunca descargar block exclude"),
    "maintenance.audit_retention_days": Field(
        doc="Días que se conserva la auditoría; `0` = siempre. La limpieza se hace una vez al día.",
        label=_l("Keep the audit log (days)"),
        page="audit_settings",
        words="auditoría retención días borrar"),
    "maintenance.backup_interval_hours": Field(
        doc=("Cada cuántas horas hace el servicio una copia de seguridad en `<data_dir>/backups`; `0` = nunca "
         "(puedes usar el timer de systemd)."),
        label=_l("Automatic backup every (hours)"),
        page="auto_backups",
        words="copia seguridad backup automática horas"),
    "maintenance.backup_keep": Field(
        doc="Copias que se conservan en `<data_dir>/backups`; las más antiguas se borran.",
        label=_l("Backups to keep"),
        page="auto_backups",
        words="copias conservar backup retención"),
    "maintenance.offsite_location": Field(
        doc="Copia **fuera del servidor**: cada copia de seguridad (automática o desde la web) se envía también a "
            "esta [ubicación de almacenamiento](../administracion/almacenamiento.md) (S3, SMB, SFTP…); vacío = no. "
            "Si el servidor se pierde, desde *Copias y base de datos* de uno nuevo con la misma ubicación se traen "
            "y se restauran.",
        label=_l("Also send backups to"),
        page="auto_backups",
        words="copia fuera remota externa offsite nube s3 nas ubicación backup"),
    "maintenance.offsite_path": Field(
        doc="Carpeta dentro de la ubicación donde se guardan las copias (se crea si no existe).",
        label=_l("Folder in the location"),
        page="auto_backups",
        words="copia remota carpeta offsite backup"),
    "maintenance.offsite_keep": Field(
        doc="Copias que se conservan en la ubicación; las más antiguas se borran (las de `antes-de-restaurar` y "
            "las subidas a mano, no).",
        label=_l("Backups to keep in the location"),
        page="auto_backups",
        words="copias conservar remota offsite retención"),
    "audit.min_level": Field(
        doc="Desde qué nivel se guarda cada evento en la auditoría: `debug` (todo: también listar carpetas, buscar, "
            "abrir en el visor, favoritos, tema e idioma), `info` (lo normal: entrar, subir, descargar, cambios), "
            "`warning` (intentos rechazados), `error` (fallos) o `critical` (incidentes de seguridad y cambios que no "
            "se deshacen). Ver los niveles de cada acción en la [referencia de la auditoría](auditoria.md).",
        label=_l("Record in the audit log from level"),
        page="audit_settings",
        words="auditoría nivel debug info warning error critical registrar guardar"),
    "audit.forward_min_level": Field(
        doc="Desde qué nivel se reenvía cada evento al syslog o al fichero JSON (`audit.syslog`, `audit.file`); por "
            "defecto, desde `info`: lo de `debug` se guarda aquí pero no llena el SIEM.",
        label=_l("Send to the SIEM from level"),
        page="audit_settings",
        words="siem syslog nivel reenviar debug info warning"),
    "audit.syslog": Field(
        doc="Reenviar cada evento de la auditoría a un **syslog o SIEM**: `udp://host:514`, `tcp://host:514` o "
            "`tls://host:6514` (RFC 5425); vacío = no. Se envía desde una cola en segundo plano: un colector lento o "
            "caído nunca frena el servicio (la auditoría sigue completa en la base de datos).",
        label=_l("Send the audit log to syslog"),
        page="audit_settings",
        words="siem syslog auditoría reenviar rsyslog splunk sentinel wazuh graylog qradar elastic"),
    "audit.syslog_format": Field(
        doc="Formato del mensaje (siempre con cabecera RFC 5424): `rfc5424` (datos estructurados), `json` (el evento "
            "en JSON) o `cef` (Common Event Format: ArcSight, QRadar, Microsoft Sentinel).",
        label=_l("Message format"),
        page="audit_settings",
        words="siem syslog formato json cef rfc5424"),
    "audit.syslog_facility": Field(
        doc="Facilidad syslog: `local0` … `local7`, `auth`, `authpriv` o `user`.",
        label=_l("Syslog facility"),
        page="audit_settings",
        words="siem syslog facility facilidad"),
    "audit.syslog_ca": Field(
        doc="Con `tls://`: fichero PEM con la CA del colector, si no la firma una de las del sistema.",
        label=_l("CA of the collector (PEM)"),
        page="audit_settings",
        words="siem syslog tls certificado ca"),
    "audit.tls_verify": Field(
        doc="Con `tls://`: comprobar el certificado del colector. Desactivarlo solo para pruebas.",
        label=_l("Check the certificate of the collector"),
        page="audit_settings",
        words="siem syslog tls certificado verificar"),
    "audit.file": Field(
        doc="Escribir también cada evento en este fichero, uno en JSON por línea, para que lo lea un agente (Filebeat, "
            "Fluent Bit, Wazuh…); vacío = no. Se abre en cada escritura, así que se puede rotar con logrotate. Como el "
            "servidor añade líneas a ese fichero: fuera de la carpeta de datos (y nunca el config.json), dentro de "
            "`storage.allowed_folders` si las hay, y una ruta de red solo si está en ellas.",
        label=_l("Also write the audit log to a JSON file"),
        page="audit_settings",
        words="siem auditoría fichero json filebeat fluent wazuh agente"),
    "metrics.enabled": Field(
        doc="Publicar métricas para Prometheus en `/metrics` (peticiones, subidas y descargas, inicios de sesión, IPs "
            "bloqueadas, espacio de las carpetas, ubicaciones remotas…).",
        label=_l("Publish metrics for Prometheus"),
        page="monitoring",
        words="métricas prometheus grafana monitorización metrics monitoring"),
    "metrics.token": Field(
        doc="Token que tiene que enviar Prometheus (`Authorization: Bearer <token>`, `bearer_token` en su "
            "configuración); al menos 16 caracteres. Nunca se muestra en la web.",
        label=_l("Metrics token"),
        page="monitoring",
        words="métricas token prometheus"),
    "metrics.allowed_networks": Field(
        doc="IPs o redes (CIDR) desde las que se puede leer `/metrics` sin token. Sin token ni redes, solo desde el "
            "propio servidor.",
        label=_l("Networks allowed to read the metrics"),
        page="monitoring",
        words="métricas redes permitidas ip prometheus"),
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
    "branding.login_art": Field(
        doc="Ilustración de serie del lateral del inicio de sesión: `classic`, `sync` (sincronización), `waves` (ondas), "
            "`mosaic` (mosaico de archivos), `layers` (capas) o `random` (una distinta en cada carga). Toma el color "
            "principal. Una imagen propia "
            "(`branding.login_image`) manda sobre ella.",
        label=_l("Sign-in illustration"),
        page="general",
        words="ilustración imagen fondo inicio sesión login marca branding illustration background"),
    "branding.login_image": Field(
        doc="Imagen del lateral del inicio de sesión: la rellena la subida desde *Sistema → General y marca* "
            "(`login.jpg`, `login.webp`…). Vacío = la ilustración de serie elegida (`branding.login_art`).",
        label=_l("Sign-in image"),
        page="general",
        words="imagen fondo inicio sesión login marca branding background image"),
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
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        # Carpetas, ubicaciones…: por su nombre; nunca su contenido (puede llevar secretos)
        return ", ".join(str(item.get("name", "?")) for item in value)[:limit]
    if isinstance(value, list):
        return ", ".join(map(str, value))[:limit]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value)[:limit]


def form_value(path: str, value):
    """Un valor tal como lo muestra el formulario de su página (para que *Restablecer* lo ponga sin guardar)."""
    info = FIELDS.get(path)
    if info is not None and info.form is not None:
        return info.form(value)
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if path == "network.public_url":
        return str(value or "").removeprefix("https://")
    return value

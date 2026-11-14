# Extender StorageWeb

Recetas para los cambios más habituales. Cada una indica también qué documentación y qué tests hay que tocar.

## Textos y traducciones

Todo texto que vea el usuario (plantillas, mensajes `flash`, errores de `core`, errores de la API, la CLI y el JavaScript) se escribe **en inglés** y pasa por la función de traducción:

=== "Python"

    ```python
    from ..i18n import _, _l, ngettext

    raise AccountError(_("A user with that name already exists."))
    flash(_("Folder «%(name)s» created.", name=name))           # parámetros con nombre, nunca f-strings
    flash(ngettext("%(num)d file uploaded.", "%(num)d files uploaded.", count))
    LABELS = {"admin": _l("Administrator")}                     # constantes de módulo: traducción diferida
    ```

=== "Plantillas Jinja"

    ```jinja
    {{ _("Upload files") }}
    {{ _("Delete «%(name)s»?", name=e.name) }}                    {# los parámetros se escapan #}
    ```

=== "JavaScript"

    Declara el texto en `web/js_messages.py` (`N_("Network error.")`) y úsalo con `t("Network error.")` o `t("HTTP error %(status)s.", {status: 500})`.

Después:

```bash
python tools/i18n.py update     # añade los textos nuevos a messages.pot y a es.po
# traduce las entradas vacías de src/storageweb/locale/es/LC_MESSAGES/messages.po
python tools/i18n.py check      # lo que ejecuta el CI
```

Reglas:

- **No** construyas frases concatenando trozos traducidos: el orden de las palabras cambia entre idiomas. Usa un único texto con parámetros.
- Los parámetros van como `%(nombre)s` y deben coincidir entre el original y la traducción (`check` lo comprueba).
- Para dar contexto al traductor, pon un comentario `# TRANSLATORS: …` en la línea anterior.
- No traduzcas los logs ni los identificadores técnicos (acciones de auditoría, nombres de opciones, rutas).

## Añadir un idioma

1. Añade el código a `LOCALES` y su nombre a `LOCALE_NAMES` en `src/storageweb/i18n.py`, por ejemplo `"pt": "Português"`.
2. `python tools/i18n.py update` crea `locale/pt/LC_MESSAGES/messages.po` con todos los textos vacíos.
3. Tradúcelos, a mano, con Poedit o con Weblate.
4. `python tools/i18n.py check` y los tests: `test_templates_have_no_hardcoded_spanish` y los de páginas en inglés sirven de modelo para el idioma nuevo.
5. Actualiza el [ADR 0010](../arquitectura/decisiones/0010-internacionalizacion.md) si cambia la política.

## Añadir una opción de configuración

1. Añade la clave con su valor por defecto en `settings/defaults.py` (`DEFAULTS`).
2. Regístrala en `settings/fields.py` (`FIELDS`): su documentación (`doc`, para la referencia) y, si se edita en la web, su etiqueta (`label`, el mismo texto que el formulario), su página (`page`, una clave de `web/nav.py`) y los sinónimos del buscador (`words`). Un test falla si falta.
3. Si necesita validación o conversión, hazla en `settings/loader.py` (`normalize`) y lanza `ConfigError` con un mensaje claro y la ruta del campo.
4. Si debe poder editarse desde la web, debe estar en una de las `RUNTIME_SECTIONS`. Añade el campo a la plantilla de su página (`web/templates/admin/settings/<sección>.html`) con `{{ origin('ruta') }}` en la etiqueta y `{{ lock('ruta') }}` en el control, y léelo en el parser de la sección (`web/views/settings/forms.py`).
5. Úsala con `settings()["seccion"]["clave"]` en la web, o recibiéndola como argumento en `core`. Su variable de entorno sale sola (`STORAGEWEB_SECCION__CLAVE`).
6. Regenera la referencia: `python tools/gen_docs.py`.

## Añadir una migración de base de datos

1. Crea `src/storageweb/db/migrations/002_descripcion.sql` con el siguiente número. **Nunca** modifiques una migración ya publicada.
2. SQL válido para SQLite, sin `BEGIN`/`COMMIT` (se añaden solos). SQLite tiene un `ALTER TABLE` limitado; para cambios complejos, crea una tabla nueva, copia los datos y renómbrala. En ese caso empieza el fichero con la línea `-- foreign_keys: off`: si no, borrar la tabla vieja borraría en cascada sus filas relacionadas (sesiones, pertenencias…). El migrador comprueba las claves ajenas antes de confirmar (ejemplo: `007_open_sources.sql`).
3. Añade o actualiza las funciones del repositorio en `db/repositories/`.
4. Los tests de `tests/unit/test_migrations.py` comprueban la numeración y la idempotencia. Añade uno con datos si la migración los transforma.
5. Actualiza [Datos](../arquitectura/datos.md) y añade una nota en el `CHANGELOG.md`.

## Añadir un método de inicio de sesión

Los métodos (local, PAM, Entra ID…) se descubren solos: **una carpeta nueva** en `src/storageweb/providers/`, sin tocar las cuentas, los grupos, el login, el Resumen, la CLI ni los ajustes.

1. Crea `providers/mi_metodo/` con un módulo (por ejemplo `method.py`) que defina una subclase de `AuthMethod` (`providers/base.py`) con su `key`, su `label` y su configuración:

    ```python
    from ...i18n import _l
    from ...settings import checks
    from ...settings.auth_methods import AuthConfig
    from ...settings.fields import Field
    from ..base import AuthMethod, Identity


    def _validate(section, cfg):                      # normaliza en el sitio o lanza ConfigError
        section["groups"] = checks.str_list(section["groups"], "auth.ldap.groups", lower=True)


    class LdapMethod(AuthMethod):
        key = "ldap"                                  # auth.ldap y users.source = "ldap"
        label = "LDAP"
        description = _l("Directory accounts (LDAP)")
        password = True                               # entra con el formulario de usuario y contraseña
        provisions = True                             # crea la cuenta en el primer inicio de sesión
        external_groups = True                        # trae grupos (pertenencias sincronizadas)
        group_hint = _l("Synchronized on each sign-in from an LDAP group.")
        config = AuthConfig(
            key="ldap",
            defaults={"enabled": False, "url": "", "bind_password": "", "groups": []},
            fields={"enabled": Field(doc="Activar LDAP.", label="LDAP", page="auth"),
                    "url": Field(doc="`ldaps://servidor`.", label=_l("Server"), page="auth"),
                    "bind_password": Field(doc="Contraseña de la cuenta de servicio.", label=_l("Password"),
                                           page="auth"),
                    "groups": Field(doc="Grupos permitidos.", label=_l("Allowed groups"), page="auth")},
            validate=_validate, secrets=("bind_password",))

        def verify(self, section, user, username, password):
            ...                                       # Identity(username, groups=[…], role=None) o None
    ```

2. **Qué sabe hacer** (atributos de `AuthMethod`): `password` (con `verify`) o `sso` (con `login_button`, `begin`, `complete` y, si cierra sesión en el proveedor, `logout_url`); `stores_password`, `provisions`, `external_groups`, `lowercase_usernames`. Opcional: `notices` (avisos del Resumen), `network_notes` (diagnóstico de red), `directory` (nombres y búsqueda de grupos). `complete` lanza `AuthDenied` si la persona no puede entrar.
3. **Configuración**: sus valores por defecto, la descripción de cada campo (`doc`, para la referencia; `label`, `page="auth"` y `words` para la web y el buscador), los secretos y su validación van en su `AuthConfig`. Se incorporan solos a `DEFAULTS["auth"]`, a la referencia generada y a las variables de entorno (`STORAGEWEB_AUTH__LDAP__URL`). Los métodos SSO usan además las opciones comunes `auto_provision`, `default_role`, `role_mappings` y `sync_role_on_login`.
4. **Ajustes**: sin hacer nada, su tarjeta en *Seguridad → Inicio de sesión* sale de `admin/settings/auth/_generic.html` (interruptor y campos de primer nivel) y el formulario se lee solo. Para una tarjeta propia, crea `admin/settings/auth/<método>.html` (y, si necesita formularios aparte, `<método>_forms.html`); para un formulario propio, registra un lector con `@auth_forms.form_parser("<método>")` en un módulo de `web/views/settings/` (como `entra.py`).
5. **SSO**: las rutas `/auth/<método>/login` y `/auth/<método>/callback` ya existen. El botón del login sale de `login_button` (texto, clase CSS e icono del sprite).
6. **Dependencias**: impórtalas dentro de las funciones (como `providers/entra/msal.py`) y declara un extra opcional en `pyproject.toml`.
7. **Tests**: `tests/unit/test_auth_methods.py` define dos métodos completos en el propio test (uno de contraseña y uno SSO) y comprueba la configuración, el login, el SSO, los grupos, el Resumen y la página de ajustes.

## Añadir un tipo de almacenamiento externo

Los tipos de ubicación (S3, SMB…) se descubren solos: basta con **un fichero nuevo** en `src/storageweb/core/backends/`, sin tocar el cargador de ajustes, las plantillas ni la documentación generada ([ADR 0014](../arquitectura/decisiones/0014-almacenamiento-externo.md)).

```python
# core/backends/webdav.py
from ...i18n import _l
from ...settings.location_types import LocationSchema, Option
from .base import RemoteBackend


class WebDAVBackend(RemoteBackend):
    schema = LocationSchema(
        kind="webdav",                       # valor de storage.locations[].type
        label=_l("WebDAV (Nextcloud, ownCloud…)"), short_label="WebDAV",
        doc="Servidor WebDAV.",              # referencia generada (en español)
        place_title=_l("Server"), extra="webdav",
        options=(
            Option("url", _l("Address"), "URL del servidor.", kind="url", required=True),
            Option("username", _l("User"), "Usuario.", section="credentials"),
            Option("password", _l("Password"), "Contraseña.", kind="secret", section="credentials"),
        ),
    )

    @classmethod
    def connect(cls, location):              # una vez por proceso y ubicación
        try:
            import webdav3.client
        except ImportError as exc:
            raise cls.missing_library("webdavclient3") from exc
        ...

    @classmethod
    def create(cls, client, location, base, staging):
        return cls(client, base, staging)    # base = ruta de la carpeta dentro de la ubicación

    @classmethod
    def address(cls, location, path=""):
        return f"{location['url'].rstrip('/')}/{path}".rstrip("/")

    # + las operaciones de Backend: stat, listdir, open (con seek), mkdir, rename, delete, store,
    #   root_exists, ensure_root (ver core/backends/base.py y s3.py como ejemplo)
```

- **Opciones** (`Option.kind`): `text`, `path` (ruta relativa, sin `..`), `url`, `secret` (nunca se muestra; vacío al editar = se conserva), `bool` y `port`. Con ellas el cargador valida, la web pinta el formulario (`section`: `place` o `credentials`) y `tools/gen_docs.py` escribe la tabla del tipo.
- **Errores:** traduce los de la biblioteca a `BackendError` con un mensaje para el usuario; `FileNotFoundError` y `FileExistsError` se dejan pasar.
- **Dependencia:** impórtala dentro de `connect` y declárala como extra en `pyproject.toml` (y en `EXTRAS` del `Dockerfile` si va en la imagen).
- **Tests:** un cliente falso en `tests/fakes.py` y el tipo en la batería común de `tests/unit/test_backends.py` (fixture `backend`). `tests/unit/test_location_types.py` muestra un tipo completo definido en el propio test.
- Después: `tools/i18n.py update` (y traducir) y `tools/gen_docs.py`.

## Añadir un endpoint de la API

1. Añade la ruta en `web/api/` (o un blueprint nuevo registrado en `web/__init__.py` con `json_api(bp)`, para que los errores salgan en JSON).
2. Descríbelo en `docs/referencia/openapi.yaml`. Un test compara las rutas de la aplicación con las de la especificación.
3. Ejecuta `python tools/gen_docs.py`.

## Añadir una acción auditada

Llama a `audit.log(conn, "mi_accion", objetivo, username=…, ip=…, detail=…)` y añade la fila en `docs/referencia/auditoria.md`. Un test busca todas las acciones del código y exige que estén documentadas.

## Añadir un comando a la CLI

1. Función `cmd_<nombre>(cfg, conn, args)` en el módulo de su grupo en `cli/` (`users.py`, `config.py`, `security.py`, `backup.py` o uno nuevo) con el decorador `@command("nombre", _l("Ayuda"), argumentos, order=…)` de `cli/common.py`. `argumentos(parser)` añade sus opciones; con `needs_db=False` la función recibe solo `args` y devuelve el código de salida. `cli/__init__.py` descubre los comandos solo.
2. Todos los textos con `_("…")` (también la ayuda de cada argumento), porque de ahí sale la [referencia](../referencia/cli.md). Después ejecuta `python tools/i18n.py update` y traduce.
3. Test en `tests/integration/test_cli.py` y `python tools/gen_docs.py`.

## Añadir un aviso al Resumen

En el módulo de `core` que sabe del asunto, registra una función con `@alerts.source("nombre", order=…)` (`core/alerts.py`). Recibe un `Context` (`cfg`, `boot`, `maint_state`, `locked`, `network`) y devuelve una lista de `alerts.alert(level, key, título, detalle, página, acción, ancla)`; `page` es una clave de `web/nav.py`. `collect` importa todo `core` antes de recorrer el registro. Ejemplos: `_missing_folders` en `core/shares.py`, `_stale_backups` en `core/maintenance.py`. Los métodos de inicio de sesión aportan los suyos con `AuthMethod.notices`.

## Añadir una tarea de mantenimiento

Con `@maintenance.task("nombre", every=lambda cfg: horas, order=…)` sobre una función `(conn, cfg)` en su módulo de `core` (ejemplo: `prune` en `core/ipban.py`). `every` devuelve cada cuántas horas toca según los ajustes (`0` = desactivada). `run_due` las ejecuta en el hilo de mantenimiento, apunta cuándo se hizo cada una en `maintenance_state` y, si una falla, la registra y sigue con las demás.

## Añadir algo al buscador (Ctrl+K)

En el módulo web de la página: `search.action(icono, _l("Título"), endpoint, args, ancla, sinónimos, order=…)` para una acción frecuente, y `@search.provider("tipo", _l("Grupo"), order=…)` sobre `fn(terms, conn, cfg)` que devuelve `search.item(...)` para buscar entidades (usa `search.matches`, que no distingue tildes). Ejemplos: usuarios en `web/views/admin/users.py`, ubicaciones en `web/views/locations.py`.

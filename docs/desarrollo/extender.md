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

1. Añade la clave con su valor por defecto en `settings/defaults.py` (`DEFAULTS`) y su descripción en `DESCRIPTIONS`. Un test falla si falta la descripción.
2. Si necesita validación o conversión, hazla en `settings/loader.py` (`normalize`) y lanza `ConfigError` con un mensaje claro.
3. Si debe poder editarse desde la web, debe estar en una de las `RUNTIME_SECTIONS`. Añade el campo en `web/templates/admin/settings.html`, con sus textos en `_()`, y léelo en `_runtime_from_form` (`web/views/admin.py`).
4. Úsala con `settings()["seccion"]["clave"]` en la web, o recibiéndola como argumento en `core`.
5. Regenera la referencia: `python tools/gen_docs.py`.

## Añadir una migración de base de datos

1. Crea `src/storageweb/db/migrations/002_descripcion.sql` con el siguiente número. **Nunca** modifiques una migración ya publicada.
2. SQL válido para SQLite, sin `BEGIN`/`COMMIT` (se añaden solos). SQLite tiene un `ALTER TABLE` limitado; para cambios complejos, crea una tabla nueva, copia los datos y renómbrala.
3. Añade o actualiza las funciones del repositorio en `db/repositories/`.
4. Los tests de `tests/unit/test_migrations.py` comprueban la numeración y la idempotencia. Añade uno con datos si la migración los transforma.
5. Actualiza [Datos](../arquitectura/datos.md) y añade una nota en el `CHANGELOG.md`.

## Añadir un proveedor SSO

1. Crea `providers/mi_proveedor.py` con una subclase de `SSOProvider`:

    ```python
    class MiProveedor(SSOProvider):
        name = "mi_proveedor"

        def begin(self, redirect_uri: str) -> tuple[str, dict]:
            ...  # URL de autorización y flow (dict serializable) para la sesión

        def complete(self, flow: dict, args: dict) -> dict:
            ...  # validar y devolver los claims (oid/sub, preferred_username, groups, roles, name, tid)
    ```

2. Regístralo en `providers/__init__.py` (`SSO_PROVIDERS`) y añade su nombre a `SSO_PROVIDER_NAMES` en `settings/defaults.py`.
3. Si usa una librería, impórtala dentro de las funciones (como hace `providers/msal.py`). Así la dependencia solo es necesaria si se activa. Declárala como extra opcional en `pyproject.toml`.
4. Tests: sustituye la llamada de red, como hace la fixture `token_endpoint`, y cubre los errores (`state`, `aud`, caducidad…).
5. Documenta la opción en [Entra ID](../administracion/entra-id.md).

## Añadir un endpoint de la API

1. Añade la ruta en `web/api/` (o un blueprint nuevo registrado en `web/__init__.py` con `json_api(bp)`, para que los errores salgan en JSON).
2. Descríbelo en `docs/referencia/openapi.yaml`. Un test compara las rutas de la aplicación con las de la especificación.
3. Ejecuta `python tools/gen_docs.py`.

## Añadir una acción auditada

Llama a `audit.log(conn, "mi_accion", objetivo, username=…, ip=…, detail=…)` y añade la fila en `docs/referencia/auditoria.md`. Un test busca todas las acciones del código y exige que estén documentadas.

## Añadir un comando a la CLI

1. Función `cmd_<nombre>(cfg, conn, args)` en `cli.py`; los guiones del comando se convierten en `_`.
2. Subparser en `build_parser()` con `help=_("…")` en el comando y en **todos** sus argumentos, porque de ahí sale la [referencia](../referencia/cli.md). Después ejecuta `python tools/i18n.py update` y traduce.
3. Test en `tests/integration/test_cli.py` y `python tools/gen_docs.py`.

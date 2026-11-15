# 0010. Internacionalización con gettext/Babel y textos fuente en inglés

- **Estado:** Aceptada
- **Fecha:** 2026-11-12

## Contexto

La primera versión tenía el español escrito directamente en las plantillas, las vistas, los mensajes de `core`, la CLI y el JavaScript. Con Entra ID el uso típico es corporativo, con usuarios que no hablan español. Hacen falta español e inglés en la web y en la CLI, y la estructura debe admitir más idiomas sin cambiar código.

## Decisión

- **gettext con Babel:** catálogos `.po` en `src/storageweb/locale/<idioma>/LC_MESSAGES/messages.po`. Es el estándar: maneja plurales, comprueba parámetros y lo entienden Poedit y Weblate.
- **Textos fuente en inglés:** el código usa `_("Upload files")`. Hay catálogo `es` y el inglés no necesita catálogo. El inglés es el respaldo de cualquier texto sin traducir.
- **`storageweb.i18n` sin Flask:** el idioma activo es una `ContextVar`.
  - La web lo fija en cada petición; la CLI lo toma del entorno.
  - Así `core` (errores de negocio) y `settings` (errores de configuración) traducen igual en la web y en la CLI, sin depender de Flask-Babel.
  - Las constantes de módulo usan traducción diferida (`_l`).
- **Elección del idioma en la web**, por este orden:
  1. preferencia del usuario (`users.locale`);
  2. idioma elegido en la sesión (selector ES/EN, también antes de iniciar sesión);
  3. `Accept-Language` del navegador;
  4. `default_locale`, que por defecto es `en` y es configurable desde la web.
- **CLI:** `STORAGEWEB_LANG`, `LC_ALL`, `LC_MESSAGES` o `LANG`; si no hay ninguno válido (por ejemplo `LANG=C.UTF-8`), inglés.
- **JavaScript:** la página incluye un `<script type="application/json">` con los textos que usa el JS, que la CSP permite porque no se ejecuta. `t()` los traduce. Los textos se declaran en `web/js_messages.py` para que la extracción los encuentre.
- **Formatos:** fechas y números con Babel según el idioma (`1,5 KB` / `1.5 KB`).
- **Sin `.mo` en el repositorio:** los `.po` se compilan en memoria la primera vez que se usan. No hay ficheros binarios versionados ni paso de compilación en los paquetes.
- **No se traduce:**
  - los **logs**, que se escriben en inglés para poder buscarlos y para el soporte;
  - la **documentación**, de momento solo en español;
  - los **identificadores** técnicos: acciones de auditoría, nombres de opciones, rutas de ficheros.
- **Comprobaciones en el CI:**
  - `tools/i18n.py check` falla si un texto no está en el catálogo, si no está traducido, si es dudoso (*fuzzy*) o si no coinciden los parámetros `%(nombre)s`;
  - un test falla si queda español escrito directamente en una plantilla;
  - otro test recorre las páginas en inglés buscando restos de español.

## Alternativas consideradas

- **Flask-Babel:** cómodo en la web, pero ata la traducción a Flask, y `core` y la CLI necesitan traducir sin aplicación.
- **Diccionarios JSON propios:** más simples al principio, pero sin plurales, sin comprobación de parámetros y sin herramientas para traductores.
- **Mantener el español como idioma fuente:** el equipo escribe más cómodo, pero las herramientas y los traductores esperan inglés, y el respaldo para idiomas sin catálogo sería español.

## Consecuencias

- Añadir un idioma es crear un `.po` y añadir su código a `LOCALES` ([receta](../../desarrollo/extender.md#anadir-un-idioma)).
- Todo texto visible nuevo debe pasar por `_()`, y hay que ejecutar `tools/i18n.py update` y traducirlo. El CI lo exige.
- Los textos fuente cambian el estilo del código: el inglés es la clave del catálogo, así que cambiar un texto en inglés invalida su traducción, como debe ser.

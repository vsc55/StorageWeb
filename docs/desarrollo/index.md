# Desarrollo

## Entorno

=== "VS Code"

    1. **Tasks: Run Task → StorageWeb: crear entorno .venv**: crea `.venv` e instala `pip install -e ".[dev]"`.
    2. **StorageWeb: crear usuario de pruebas**: pregunta el nombre y el rol (por defecto `admin`).
    3. **Ctrl+Shift+B** → servidor de pruebas en http://127.0.0.1:8080, que se **reinicia solo** al cambiar `.py`, la configuración o las plantillas.
    4. **F5 → Depurar servidor**: con breakpoints, sin recarga automática.

=== "Terminal"

    ```bash
    python -m venv .venv && .venv/bin/pip install -e ".[dev,docs]"
    storageweb --config config/config.dev.json user-add admin --role admin
    storageweb --config config/config.dev.json serve --dev
    ```

`config/config.dev.json` guarda todo en `.dev/` (ignorado por git), funciona con HTTP y crea las carpetas compartidas.

## Estructura

```
src/storageweb/   settings · db · providers (local/ · pam/ · entra/) · core · web (views, api, templates, static) · cli/
tests/            unit/ (sin Flask) · integration/ (app completa) · helpers.py · sso_helpers.py
docs/             esta documentación (MkDocs)
tools/            gen_docs.py
packaging/        install.sh · build.sh · nfpm · systemd · nginx · apache · docker · gentoo
```

Las capas y el porqué de esta organización están en [Arquitectura](../arquitectura/index.md).

## Convenciones

- **Capas:** `core`, `db`, `providers` y `settings` **no importan Flask**. Los repositorios reciben la conexión como primer argumento (`users.get_by_id(conn, uid)`). En las vistas, la conexión se obtiene con `web.context.get_db()` y la configuración con `web.context.settings()`.
- **Errores de negocio** como excepciones propias (`AccountError`, `UploadError`, `BackupError`, `ConfigError`), que la capa web traduce a HTTP.
- **Seguridad primero:**
  - toda ruta que venga del usuario pasa por `resolve_inside` o `resolve_entry`, y todo nombre por `safe_filename`;
  - cada acción comprueba permisos en el servidor;
  - las acciones relevantes se registran con `audit.log` y se documentan en la [referencia de auditoría](../referencia/auditoria.md); hay un test que lo exige.
- **Textos e idiomas:** todo texto visible pasa por `_()` y está escrito **en inglés** (es la clave del catálogo); la traducción al español va en `locale/es/LC_MESSAGES/messages.po`. Más detalle en [Textos y traducciones](extender.md#textos-y-traducciones). Los logs se escriben en inglés y no se traducen. La documentación está en español.
- **Compatibilidad:** Python 3.9+ (`from __future__ import annotations`) y Linux, Windows y macOS (`pathlib`, nada de rutas con `/` a mano).
- **Estilo:** líneas de hasta 100–110 caracteres, docstrings en los módulos y en las funciones no evidentes.
- **JavaScript de terceros:** solo Mermaid (diagramas del visor), copiado en `src/storageweb/web/static/vendor/` con `python tools/vendor.py`. El script descarga una versión fija del registro de npm, comprueba su huella SHA-512 y extrae solo los ficheros que se usan, sin npm ni pnpm y sin ejecutar nada del paquete. Las huellas de los ficheros extraídos están en el script: `tools/vendor.py --check` (también lo hace un test) avisa si alguien los cambia a mano. Para actualizarlo, cambia la versión y la huella del paquete en el script y ejecútalo.

## Tests

```bash
python -m pytest -q                # todos (~330 tests, ~2 min)
python -m pytest -q tests/unit     # unitarios, ~3 s
python -m pytest -q -k uploads     # filtrar
```

- **`tests/unit/`:** lógica pura con SQLite directo (fixture `db_conn`): settings, migraciones, cuentas, OAuth2, subidas, copias, i18n, empaquetado y documentación.
- **`tests/integration/`:** la aplicación con el cliente de pruebas de Flask. Fixtures `make_app(overrides)`, `logged` (usuario `ana`) y `admin` (usuario `root`). Entra ID se simula sustituyendo `oauth2._http_post` (fixture `token_endpoint`).
- **CI:** los tests se ejecutan en Ubuntu, Windows y macOS con la última versión de Python (3.14). Las anteriores que admite el proyecto (desde 3.9) no se prueban en el CI: ojo con sintaxis o bibliotecas que no existan en ellas. Los tests con symlinks se omiten donde el sistema no permite crearlos.

Siguiente: [Extender StorageWeb](extender.md) · [Documentación](documentacion.md) · [Releases](releases.md).

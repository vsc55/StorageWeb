# Documentación

La documentación se trata como código: vive en el repositorio (`docs/`), se revisa en los pull requests, se comprueba en el CI y se publica con cada release.

## Organización

Sigue el modelo [Diátaxis](https://diataxis.fr/): cada página tiene un único propósito.

| Sección | Tipo | Para quién |
|---|---|---|
| Uso | Guía | Usuarios finales |
| Administración | Guías prácticas (*cómo hacer X*) | Quien instala y opera |
| Referencia | Descripción exhaustiva y exacta | Consulta puntual |
| Arquitectura | Explicación: el porqué (ADR) | Desarrolladores, revisores |
| Desarrollo | Guías para contribuir | Desarrolladores |

## Referencia generada

Estas páginas **no se editan a mano**. Se generan desde el código con `tools/gen_docs.py`:

| Página | Fuente |
|---|---|
| `referencia/configuracion.md` | `DEFAULTS` de `settings/defaults.py`, `FIELDS` de `settings/fields.py` y las variables de `settings/env.py` |
| `referencia/cli.md` | `build_parser()` de `cli/__init__.py` |
| `referencia/api.md` | `docs/referencia/openapi.yaml` |

```bash
python tools/gen_docs.py           # regenerar
python tools/gen_docs.py --check   # lo que ejecuta el CI: falla si algo está desactualizado
```

Además, `tests/unit/test_docs.py` comprueba lo siguiente:

- que todas las opciones de configuración tienen descripción;
- que las rutas de `openapi.yaml` coinciden con las de la aplicación;
- que todas las acciones de auditoría del código están en `referencia/auditoria.md`;
- que todas las páginas están en la navegación.

## Ver y construir

```bash
pip install -e ".[docs]"
mkdocs serve                 # http://127.0.0.1:8000, con recarga automática
mkdocs build --strict        # falla con enlaces rotos (lo ejecuta el CI)
```

También están las tareas de VS Code **StorageWeb: documentación (servir)** y **StorageWeb: regenerar referencia**.

## Capturas de pantalla

Las capturas de `docs/img/` (`uso/` y `admin/`) salen de una **instalación de demostración con datos inventados** y se regeneran con un comando cuando cambia la interfaz:

```bash
python tools/screenshots/demo.py                # todas, a docs/img/
python tools/screenshots/demo.py --only admin/  # solo las que empiezan así
python tools/screenshots/demo.py --serve        # solo la demo en marcha, para mirarla (ana.garcia / demo-1234)
```

- `tools/screenshots/demo.py` crea la demo en una carpeta temporal: ocho personas, cuatro grupos (dos de Entra ID), cuatro carpetas compartidas con archivos, sesiones, tokens, reglas de IP, auditoría y una copia de seguridad. Todo es inventado, también las direcciones (rangos de documentación `192.0.2.0/24`, `198.51.100.0/24` y `203.0.113.0/24`) y el tenant de Entra ID. No toca la instalación de desarrollo.
- La demo **no sale del equipo**: cualquier conexión que no sea local falla al momento, así que nunca habla con Microsoft. Funciona como detrás de un proxy HTTPS en `https://archivos.ejemplo.com`, las carpetas se ven bajo `/srv/storageweb` y el disco es de 2 TB, aunque todo esté en la carpeta temporal de tu equipo; ninguna ruta tuya aparece en las capturas.
- `tools/screenshots/capture.mjs` maneja **Edge o Chrome sin ventana** por su protocolo de depuración, con Node 18 o posterior y sin dependencias: inicia sesión, abre cada página, hace lo que pida la captura (seleccionar archivos, abrir el buscador…) y la guarda en WebP. El navegador se busca en las rutas habituales o en `STORAGEWEB_BROWSER`, y Node en `STORAGEWEB_NODE`.
- Qué se captura está en la lista `plan()` de `demo.py`. Una captura nueva es una línea más (`file`, `path`, el usuario con el que entra y, si hace falta, el JavaScript que prepara la pantalla), y luego se enlaza desde la página con `![texto](../img/…)`.

## Publicación

El workflow de release publica el sitio en **GitHub Pages**. Requiere activar *Settings → Pages → Source: GitHub Actions* en el repositorio.

## Idioma

La documentación está **solo en español**; la interfaz y la CLI están en español e inglés ([ADR 0010](../arquitectura/decisiones/0010-internacionalizacion.md)). Si en el futuro se traduce, el plan es usar `mkdocs-static-i18n`, con ficheros `pagina.en.md` junto a cada página, sin cambiar la estructura.

## Estilo

- Español, en segunda persona («instala», «comprueba»). Frases cortas y comandos copiables.
- Cada guía empieza por el objetivo y termina con cómo comprobar que funcionó.
- Avisos `!!! warning` solo para riesgos reales: pérdida de datos o seguridad.
- Los diagramas van en Mermaid, dentro del Markdown, para que se versionen con el texto. MkDocs no comprueba su sintaxis: mira la página en `mkdocs serve` antes de dar uno por bueno.
- Las pantallas, con capturas reales (ver *Capturas de pantalla*), nunca dibujadas con texto.
- Las decisiones nuevas se registran como [ADR](../arquitectura/decisiones/index.md).

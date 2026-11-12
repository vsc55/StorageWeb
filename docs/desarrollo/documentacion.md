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
| `referencia/configuracion.md` | `DEFAULTS` y `DESCRIPTIONS` de `settings/defaults.py` |
| `referencia/cli.md` | `build_parser()` de `cli.py` |
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

## Publicación

El workflow de release publica el sitio en **GitHub Pages**. Requiere activar *Settings → Pages → Source: GitHub Actions* en el repositorio.

## Idioma

La documentación está **solo en español**; la interfaz y la CLI están en español e inglés ([ADR 0010](../arquitectura/decisiones/0010-internacionalizacion.md)). Si en el futuro se traduce, el plan es usar `mkdocs-static-i18n`, con ficheros `pagina.en.md` junto a cada página, sin cambiar la estructura.

## Estilo

- Español, en segunda persona («instala», «comprueba»). Frases cortas y comandos copiables.
- Cada guía empieza por el objetivo y termina con cómo comprobar que funcionó.
- Avisos `!!! warning` solo para riesgos reales: pérdida de datos o seguridad.
- Los diagramas van en Mermaid, dentro del Markdown, para que se versionen con el texto.
- Las decisiones nuevas se registran como [ADR](../arquitectura/decisiones/index.md).

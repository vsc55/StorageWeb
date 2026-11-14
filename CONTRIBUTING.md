# Contribuir

¡Gracias por ayudar! Esta guía resume cómo proponer cambios. El detalle está en la documentación de desarrollo (`docs/desarrollo/`).

## Flujo

1. Abre un issue para hablar de cambios grandes antes de programarlos.
2. Crea una rama desde la principal: `feat/…`, `fix/…`, `docs/…`.
3. Prepara el entorno: `pip install -e ".[dev,docs]"`, o la tarea de VS Code *crear entorno .venv*.
4. Haz el cambio **con sus tests y su documentación**.
5. Comprueba en local:
   ```bash
   python -m pytest -q
   python tools/gen_docs.py --check
   python tools/i18n.py check
   mkdocs build --strict
   node --test clients/vscode/test      # si tocas la extensión de VS Code (Node 18+, sin npm)
   ```
6. Abre un pull request describiendo qué cambia y por qué, y añade una entrada en `CHANGELOG.md` → *Sin publicar*.

## Qué se revisa

- [ ] Respeta las capas: nada de Flask fuera de `web/`; los repositorios reciben la conexión.
- [ ] Las rutas y los nombres que vienen del usuario pasan por `resolve_inside` / `safe_filename`.
- [ ] Los permisos se comprueban en el servidor y las acciones relevantes se auditan.
- [ ] Tests: unitarios para la lógica y de integración para el HTTP.
- [ ] Textos visibles en inglés y con `_()`, catálogo actualizado (`tools/i18n.py update`) y traducido al español.
- [ ] Documentación actualizada (y referencia regenerada si cambian la configuración, la CLI o la API).
- [ ] Un ADR si es una decisión de arquitectura (`docs/arquitectura/decisiones/`).
- [ ] Una migración nueva si cambia el esquema; nunca se modifica una publicada.

## Commits

Mensajes en español, en imperativo y con prefijo de tipo: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`. Ejemplo: `fix: no seguir symlinks al renombrar`.

## Seguridad

No informes de vulnerabilidades en issues públicos; consulta `SECURITY.md`.

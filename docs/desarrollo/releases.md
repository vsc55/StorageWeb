# Releases

## Versionado

[Versionado semántico](https://semver.org/lang/es/) `MAYOR.MENOR.PARCHE`, con sufijos de *pre-release* (`1.3.0-rc1`). Se consideran **API pública**, y por tanto un cambio incompatible en ellos sube la versión mayor:

- las opciones de `config.json`;
- los comandos de la CLI;
- la API HTTP (`openapi.yaml`);
- el formato de las copias de seguridad;
- las rutas de instalación.

Mientras el proyecto esté en la serie **0.x** (desarrollo inicial), un cambio incompatible sube la versión **menor** (`0.1.0` → `0.2.0`) y las correcciones la de parche (`0.2.1`), siempre con su aviso en el `CHANGELOG.md`. La `1.0.0` será la primera versión estable, con el compromiso de arriba.

La extensión de VS Code tiene **su propia versión**, la de `clients/vscode/package.json`, y la release la adjunta con ella (`storageweb-sync-<versión de la extensión>.vsix`). Súbela cuando cambie la extensión: VS Code no reinstala un `.vsix` con la misma versión.

## Publicar una versión

1. Mueve las entradas de `## [Sin publicar]` del `CHANGELOG.md` a `## [X.Y.Z] - AAAA-MM-DD`. Esa sección es el texto de la release (`python tools/release_notes.py X.Y.Z` la muestra); sin ella, el workflow se para antes de publicar nada.
2. Actualiza `__version__` en `src/storageweb/__init__.py`.
3. Haz commit en la rama principal y crea la etiqueta:
   ```bash
   git tag vX.Y.Z && git push origin HEAD vX.Y.Z
   ```

El workflow `release.yml` hace el resto:

| Job | Qué hace |
|---|---|
| `tests` | Toda la CI: tests en 3 sistemas, scripts, wheel, imagen Docker, extensión de VS Code, documentación y traducciones |
| `build` | Wheel, zip y tar.gz, `.deb` y `.rpm` (amd64 y arm64), overlay de Gentoo y la extensión de VS Code (`storageweb-sync-<versión>.vsix`, con la suya). Instala el `.deb` en el runner y lo prueba |
| `docker` | Imagen multi-arquitectura en `ghcr.io/vsc55/storageweb` (`X.Y.Z`, `X.Y`, `latest`) |
| `gentoo` | `emerge` del ebuild en `gentoo/stage3`. Informativo: no bloquea la release |
| `docs` | Publica la documentación en GitHub Pages |
| `release` | Crea la release de GitHub con los ficheros y, como texto, la sección de la versión del `CHANGELOG.md` |

Los tags con sufijo se publican como *pre-release* y no mueven `latest`.

Si una release ya publicada necesita rehacerse (por ejemplo, un fallo del propio workflow), se puede mover su tag al commit nuevo (`git tag -f vX.Y.Z && git push -f origin vX.Y.Z`): el job `release` ve que ya existe y la **actualiza** (texto, ficheros nuevos y fuera los que ya no se generan) en lugar de fallar. La imagen Docker de esa versión se sustituye.

## Probar sin publicar

*Actions → Release → Run workflow*, con una versión de prueba (por ejemplo `0.0.0-dev`). Genera todos los artefactos como *artifact* del workflow, sin crear la release ni subir la imagen.

En local, en Linux con `nfpm`:

```bash
packaging/build.sh 1.2.0 amd64
```

## Requisitos del repositorio

- *Settings → Pages → Source: GitHub Actions*, para la documentación.
- Permisos de *packages* para `GITHUB_TOKEN` (por defecto en repositorios personales), para GHCR.

# Releases

## Versionado

[Versionado semántico](https://semver.org/lang/es/) `MAYOR.MENOR.PARCHE`, con sufijos de *pre-release* (`1.3.0-rc1`). Se consideran **API pública**, y por tanto un cambio incompatible en ellos sube la versión mayor:

- las opciones de `config.json`;
- los comandos de la CLI;
- la API HTTP (`openapi.yaml`);
- el formato de las copias de seguridad;
- las rutas de instalación.

## Publicar una versión

1. Mueve las entradas de `## [Sin publicar]` del `CHANGELOG.md` a `## [X.Y.Z] - AAAA-MM-DD`.
2. Actualiza `__version__` en `src/storageweb/__init__.py`.
3. Haz commit en la rama principal y crea la etiqueta:
   ```bash
   git tag vX.Y.Z && git push origin HEAD vX.Y.Z
   ```

El workflow `release.yml` hace el resto:

| Job | Qué hace |
|---|---|
| `tests` | Toda la CI: tests en 3 sistemas, scripts, wheel, imagen Docker, extensión de VS Code, documentación y traducciones |
| `build` | Wheel, zip y tar.gz, `.deb` y `.rpm` (amd64 y arm64), overlay de Gentoo y la extensión de VS Code (`storageweb-sync-X.Y.Z.vsix`, con la misma versión). Instala el `.deb` en el runner y lo prueba |
| `docker` | Imagen multi-arquitectura en `ghcr.io/<owner>/<repo>` (`X.Y.Z`, `X.Y`, `latest`) |
| `gentoo` | `emerge` del ebuild en `gentoo/stage3`. Informativo: no bloquea la release |
| `docs` | Publica la documentación en GitHub Pages |
| `release` | Crea la release de GitHub con los ficheros y las notas generadas |

Los tags con sufijo se publican como *pre-release* y no mueven `latest`.

## Probar sin publicar

*Actions → Release → Run workflow*, con una versión de prueba (por ejemplo `0.0.0-dev`). Genera todos los artefactos como *artifact* del workflow, sin crear la release ni subir la imagen.

En local, en Linux con `nfpm`:

```bash
packaging/build.sh 1.2.0 amd64
```

## Requisitos del repositorio

- *Settings → Pages → Source: GitHub Actions*, para la documentación.
- Permisos de *packages* para `GITHUB_TOKEN` (por defecto en repositorios personales), para GHCR.

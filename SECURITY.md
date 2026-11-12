# Política de seguridad

## Versiones con soporte

Se publican correcciones de seguridad para la **última versión menor** publicada. Por ejemplo, si la última es 1.4.x, las correcciones salen como 1.4.y.

## Informar de una vulnerabilidad

**No abras un issue público.** Usa el aviso privado de GitHub: *Security → Report a vulnerability* en el repositorio. Incluye:

- la versión afectada y el tipo de instalación (deb/rpm, Docker, Gentoo, código);
- los pasos para reproducirla y el impacto que crees que tiene;
- si la información es sensible, una prueba de concepto mínima.

Compromisos:

| Plazo | Acción |
|---|---|
| 3 días laborables | Acuse de recibo |
| 10 días laborables | Evaluación inicial y gravedad (CVSS) |
| Según gravedad | Corrección, release y aviso publicado (GitHub Security Advisory), con reconocimiento si lo deseas |

## Alcance

Están dentro del alcance la aplicación (`src/storageweb`), los paquetes, la imagen Docker y los scripts de `packaging/`.

Quedan fuera:

- configuraciones inseguras documentadas como tales, por ejemplo `cookie_secure = false` o `behind_proxy` sin proxy;
- vulnerabilidades de dependencias que ya tienen versión corregida (avísanos para publicar una release);
- ataques que requieren acceso de root al servidor.

El modelo de amenazas y los controles están en `docs/arquitectura/seguridad.md`.

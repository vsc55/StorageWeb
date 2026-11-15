# Decisiones de arquitectura (ADR)

Un ADR (*Architecture Decision Record*) explica **por qué** se tomó una decisión importante: el contexto, las alternativas y las consecuencias. El código dice *qué* se hace; los ADR evitan que, años después, alguien deshaga una decisión sin saber por qué se tomó.

| Nº | Decisión | Estado |
|---|---|---|
| [0001](0001-python-flask-waitress.md) | Python, Flask y Waitress | Aceptada |
| [0002](0002-paquete-y-capas.md) | Paquete `src/storageweb` y capas sin Flask | Aceptada |
| [0003](0003-oauth2-propio.md) | Proveedor OAuth2/OIDC propio por defecto; MSAL opcional | Aceptada |
| [0004](0004-firma-id-token.md) | No verificar la firma del id_token | Aceptada |
| [0005](0005-ajustes-web-sqlite.md) | Ajustes web en SQLite con prioridad sobre `config.json` | Sustituida en parte por 0013 |
| [0006](0006-subidas-por-partes.md) | Subidas por partes reanudables | Aceptada |
| [0007](0007-migraciones.md) | Migraciones SQL versionadas con `PRAGMA user_version` | Aceptada |
| [0008](0008-empaquetado.md) | Paquetes con wheel + venv y dependencias incluidas | Aceptada |
| [0009](0009-usuario-de-servicio.md) | Un solo usuario de servicio para todos los archivos | Aceptada |
| [0010](0010-internacionalizacion.md) | Internacionalización con gettext/Babel y textos fuente en inglés | Aceptada |
| [0011](0011-grupos-gestionados.md) | Grupos gestionados con pertenencias manuales y sincronizadas | Aceptada |
| [0012](0012-administracion-por-zonas.md) | Administración por zonas con Resumen y buscador | Aceptada |
| [0013](0013-capas-de-configuracion.md) | Capas de configuración: web < config.json < entorno | Aceptada (el almacenamiento, sustituido por 0017) |
| [0014](0014-almacenamiento-externo.md) | Almacenamiento externo: backends por raíz | Aceptada |
| [0015](0015-extensiones-que-se-descubren.md) | Extensiones que se registran solas | Aceptada |
| [0016](0016-conectar-aplicaciones-con-el-navegador.md) | Conectar aplicaciones iniciando sesión en el navegador (PKCE) | Aceptada |
| [0017](0017-ajustes-web-por-campo.md) | Ajustes web por campo, una fila por perfil y campo | Aceptada |
| [0018](0018-carpetas-y-ubicaciones-como-entidades.md) | Carpetas compartidas, ubicaciones y cuotas de grupo como entidades | Aceptada |

## Cómo proponer uno

1. Copia la [plantilla](plantilla.md) como `NNNN-titulo-corto.md`, con el siguiente número.
2. Estado *Propuesta*; discútelo en el pull request.
3. Al aprobarlo, pasa a *Aceptada*. Los ADR no se borran: si una decisión cambia, se escribe uno nuevo que la *sustituye* y se actualiza el estado del anterior.

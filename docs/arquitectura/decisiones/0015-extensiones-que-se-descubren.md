# 0015. Extensiones que se registran solas

- **Estado:** Aceptada
- **Fecha:** 2026-11-14
- **Amplía:** [0014](0014-almacenamiento-externo.md) (los tipos de almacenamiento fueron el primer caso)

## Contexto

Varias partes del código general enumeraban a mano cosas que pertenecen a otro módulo:

- **Métodos de inicio de sesión.** `local`, `pam` y `entra` aparecían en unos quince sitios: los valores por defecto, la validación y la documentación de `auth.*`, las cuentas, los grupos, el login, la página de ajustes, el Resumen, el diagnóstico de red, la CLI, las plantillas y hasta un `CHECK` de la base de datos. Añadir LDAP o SAML (hoja de ruta) obligaba a tocarlos todos.
- **Avisos del Resumen.** `core/alerts.collect` mezclaba el secreto de Entra, las carpetas que faltan, las copias y la red.
- **Tareas de mantenimiento.** `run_due` tenía fijas la limpieza, la purga de la auditoría y las copias.
- **Buscador (Ctrl+K).** Las acciones y las entidades estaban en una sola función; las ubicaciones de almacenamiento, recién añadidas, no aparecían.
- **CLI.** Una lista de comandos y un `build_parser` con los argumentos de todos.

## Decisión

Cada cosa se **declara en el módulo que sabe de ella** y un registro la recoge. `storageweb.registry.import_submodules(paquete)` importa los módulos de un paquete antes de recorrer su registro, sin listas a mano.

| Registro | Se declara con | Dónde | Lo recorre |
|---|---|---|---|
| Métodos de inicio de sesión | subclase de `providers.AuthMethod` con `key` y `config` | `providers/<método>/` | `providers.methods()` |
| Su configuración | `settings.auth_methods.AuthConfig` (valores, campos, secretos, validación) | en el propio método | cargador, `fields`, referencia generada |
| Tipos de almacenamiento | subclase de `RemoteBackend` con `schema` | `core/backends/<tipo>.py` | `core.backends.TYPES` |
| Avisos del Resumen | `@alerts.source` | el módulo de `core` del asunto | `alerts.collect` |
| Tareas de mantenimiento | `@maintenance.task` | ídem | `maintenance.run_due` |
| Comandos de la CLI | `@command` (`cli/common.py`) | `cli/<grupo>.py` | `cli.build_parser` |
| Buscador | `search.action`, `@search.provider` | el módulo web de la página | `search.find` |

Además:

- **Capas.** `settings` no importa a nadie: los métodos de inicio de sesión registran su configuración en `settings.auth_methods`, como los tipos de almacenamiento en `settings.location_types`. El **punto de ensamblado** es `storageweb/__init__.py`, que importa `core` y `providers` antes que nada, así que la configuración por defecto y su validación ya incluyen lo registrado.
- **Base de datos.** `users.source` y `groups.source` no limitan la lista de métodos con un `CHECK`. El migrador admite migraciones que reconstruyen tablas (`-- foreign_keys: off` y comprobación de claves ajenas antes de confirmar).
- **Interfaz.** La página *Inicio de sesión* pinta una tarjeta por método: la plantilla del método si la tiene (`auth/<método>.html`) o una genérica construida con su configuración. El login muestra un botón por método SSO; las rutas son `/auth/<método>/login` y `/auth/<método>/callback` (para Entra ID, la misma dirección de vuelta de siempre).
- **Se mantiene centralizado** lo que es una decisión de diseño y conviene ver en un solo sitio: la navegación de la administración (`web/nav.py`, [0012](0012-administracion-por-zonas.md)), el registro de blueprints y las secciones de ajustes.

## Alternativas consideradas

- **Entry points de Python** para todos los registros: permitirían extensiones en otros paquetes, pero obligan a reinstalar al añadir una y complican el desarrollo. Los registros tienen `register()` por si algún día hace falta.
- **Formularios de ajustes totalmente genéricos** para todos los métodos: Entra ID tiene asistente, registro automático, prueba de conexión y mapeo de roles; forzarlo a un formulario genérico empeoraría su página. Por eso cada método puede traer su plantilla y su lector de formulario, y el genérico queda para los sencillos.
- **Dejar el `CHECK` y añadir una migración por método nuevo:** contradice el objetivo; la validez del origen ya la garantiza el registro.

## Consecuencias

- Añadir un método de inicio de sesión, un tipo de almacenamiento, un aviso, una tarea, un comando o un resultado del buscador no toca código general ([Extender StorageWeb](../../desarrollo/extender.md)). Los tests `test_auth_methods.py`, `test_location_types.py` y `test_extensions.py` lo comprueban con extensiones definidas en el propio test.
- Importar `storageweb` carga `core` y `providers` (sin Flask). Es lo que ya hacían la aplicación y la CLI.
- Las rutas `auth.entra_login` y `auth.entra_callback` pasan a ser `auth.sso_login` y `auth.sso_callback` con `method="entra"`; las direcciones no cambian.

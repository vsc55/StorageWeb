# 0013. Capas de configuración: web < config.json < entorno

- **Estado:** Aceptada
- **Fecha:** 2026-11-14
- **Sustituye en parte a:** [0005](0005-ajustes-web-sqlite.md) (el orden de prioridad)

## Contexto

Según [0005](0005-ajustes-web-sqlite.md), los ajustes web ganaban sobre `config.json`. Eso tenía tres problemas:

- **Lo fijado por automatización no era fijo.** Quien despliega con Ansible o Kubernetes no puede fijar un valor: cualquier admin lo cambia en la web y el fichero deja de mandar sin que se note.
- **Docker solo usaba las variables una vez.** Las variables de entorno servían para generar `config.json` en el primer arranque y luego se ignoraban.
- **«Restablecer» no llevaba al predeterminado.** Volvía al valor de `config.json`. No había forma de saber qué ajustes no tenían su valor predeterminado.

## Decisión

- **Cuatro capas, campo a campo,** de menor a mayor prioridad: valores predeterminados < ajustes web (SQLite) < `config.json` < variables de entorno.
- **Bloqueo.** Lo que fijan `config.json` o una variable está **bloqueado** en la web: se muestra con su origen y no se puede cambiar ni restablecer. Los formularios lo desactivan y `RuntimeSettings.save` lo descarta. Los cambios hechos por código (matriz, carpetas, logo, Entra ID) usan `strict` y fallan con un mensaje que dice dónde está fijado.
- **Variables de entorno.** `STORAGEWEB_` + la ruta en mayúsculas con `__` entre niveles; listas y objetos en JSON. Se mantienen como alias los nombres cortos de Docker. Se leen en cada arranque.
- **Lo que se guarda.** Los ajustes web son la diferencia mínima con los **valores predeterminados**, sin los campos bloqueados. *Restablecer* vuelve al predeterminado. La web marca como **modificado** lo que no es predeterminado y lo cuenta por página.
- **Perfiles.** `settings_profile` elige la clave de la tabla `settings` (`runtime` para `default`, `runtime:<perfil>` para los demás). Así varias instancias pueden compartir base de datos con ajustes distintos, como con varios `config.json`.
- **Ficheros mínimos.** El `config.json` de los paquetes y el que genera Docker solo llevan lo de arranque y la plantilla de las carpetas personales.

## Alternativas consideradas

- **Mantener la web por encima de `config.json`:** no permite fijar nada desde fuera.
- **Importar `config.json` a la base de datos al arrancar:** reescribiría un fichero gestionado por el admin. Además, como aún no había instalaciones en producción, no hacía falta migrar.
- **Una columna de perfil en la tabla `settings`:** la clave ya identifica el documento; un prefijo en la clave evita una migración.

## Consecuencias

- Un campo de `config.json` deja de ser editable en la web. Quien quiera editarlo desde la web debe quitarlo del fichero.
- Los tests guardan los ajustes editables en la base de datos (`tests/conftest.py::make_app`). Para probar bloqueos, escriben `config.json` a mano.
- Las variables de entorno con un valor no válido impiden arrancar, con un error que nombra la variable.

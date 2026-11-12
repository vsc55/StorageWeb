# 0002. Paquete `src/storageweb` y capas sin Flask

- **Estado:** Aceptada
- **Fecha:** 2026-11-12

## Contexto

La primera versión tenía el código en `src/`, que se importaba como paquete llamado `src`. Las rutas, la lógica, el acceso a datos y las plantillas estaban mezclados. Tenía tres problemas:

- un paquete llamado `src` choca con otros proyectos si se instala con pip;
- no se podían declarar comandos (*entry points*);
- la lógica dependía de Flask (`flask.g`), lo que dificultaba las pruebas.

## Decisión

- **Estructura:** *src layout* estándar, con el paquete en `src/storageweb/` y `pyproject.toml` como única fuente de dependencias y del comando `storageweb`.
- **Capas** con dependencias en un solo sentido: `web → core → db/providers → settings`.
- **Sin Flask fuera de `web/`:** los repositorios de `db/` reciben la conexión SQLite como argumento, y `web/context.py` es el único punto que une Flask con el resto.
- **Frontend:** `templates/` y `static/` dentro del paquete (`web/`), de modo que viajan con el wheel, separados del Python.
- **Web dividida:** `web/views/` (HTML) y `web/api/` (JSON, con errores en JSON).

## Alternativas consideradas

- **Mantener `src` como paquete:** más corto de escribir, pero con los problemas anteriores.
- **Frontend fuera del paquete:** obliga a localizarlo con rutas relativas a la raíz del repositorio, que se rompen al instalar.

## Consecuencias

- `pip install` funciona y el comando `storageweb` queda instalado.
- `tests/unit` prueba la lógica con SQLite directo, sin servidor.
- Hay que pasar la conexión explícitamente, lo que es algo más verboso.

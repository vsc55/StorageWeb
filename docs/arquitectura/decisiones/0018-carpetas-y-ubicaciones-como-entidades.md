# 0018. Carpetas compartidas, ubicaciones y cuotas de grupo como entidades

- **Estado:** Aceptada
- **Fecha:** 2026-11-15

## Contexto

Con los ajustes ya guardados por campo ([0017](0017-ajustes-web-por-campo.md)), quedaban tres «campos» que en realidad son colecciones de cosas con identidad propia, guardadas como un JSON grande en una sola fila:

- `storage.shares`: las carpetas compartidas, cada una con su ruta, su ubicación, su cuota y la lista de quién entra;
- `storage.locations`: las conexiones a S3, SMB, SFTP…, cada una con opciones distintas según su tipo y con secretos;
- `storage.group_quotas`: un diccionario grupo → MB, que es un dato del grupo.

Cambiar una carpeta reescribía la lista entera; no se sabía quién cambió cuál; y si una lista estaba en `config.json`, la página entera quedaba bloqueada aunque solo se quisiera añadir otra.

## Decisión

Tablas propias: `shares` + `share_access` (quién entra: todos, un usuario o un grupo, con lectura o escritura, una fila por acceso), `locations` + `location_options` (las opciones dependen del tipo: una fila por opción, los secretos cifrados) y la columna `groups.home_quota_mb`. Carpetas y ubicaciones son por perfil, como los ajustes; la cuota es del grupo, que es común a todos.

- **config.json y el entorno siguen valiendo, de solo lectura:** sus carpetas y ubicaciones se ven junto a las de la web, marcadas con su origen (`origin` = `file`/`env`), y no se pueden cambiar ni borrar desde la web; las de la web (`origin` = `web`) sí. Si un nombre está en los dos sitios, manda `config.json`. Lo mismo con la cuota de cada grupo.
- **Validación conjunta:** una carpeta de la web puede usar una ubicación de `config.json` y al revés; se validan juntas, como antes.
- **La forma de la configuración efectiva no cambia:** `cfg["storage"]["shares"]` y `["locations"]` siguen siendo listas (ahora con `origin`), así que todo el código que las lee sigue igual. Lo que cambia es dónde se guardan: `RuntimeSettings.save` reparte, y las entidades se escriben **por nombre**, solo las que cambian respecto a lo que quien guarda tenía en pantalla (`base`), como los campos en la 0017.

## Alternativas consideradas

- **Que config.json siembre las tablas al arrancar y desde ahí se gestione todo en la web:** una sola fuente, pero el fichero dejaría de mandar sin que quien lo edita lo note (un cambio en `config.json` no se aplicaría a una carpeta ya sembrada).
- **Dejar de leerlas de config.json:** lo más simple, pero rompe las instalaciones (Docker, Ansible) que las declaran en el fichero.
- **Opciones de las ubicaciones como columnas:** cada tipo tiene las suyas y los tipos se descubren (0014, 0015); una tabla nombre → valor no necesita migraciones al añadir un tipo.

## Consecuencias

- Cambiar una carpeta toca sus filas y nada más; cada carpeta y cada ubicación sabe quién y cuándo la cambió.
- Se pueden añadir carpetas desde la web aunque haya otras fijadas en `config.json`.
- Varias instancias con la misma base de datos y perfiles distintos tienen carpetas y ubicaciones propias, pero comparten las cuotas de grupo (los grupos son comunes).
- Los valores de las opciones de una ubicación siguen siendo JSON de un valor simple (texto, número o booleano) para conservar su tipo.

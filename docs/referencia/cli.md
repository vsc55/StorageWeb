<!-- Generado por tools/gen_docs.py: no editar a mano -->

# Referencia de la CLI

Comando `storageweb` (también `python -m storageweb`). En un servidor instalado con paquetes, usa `sudo storageweb-admin <comando>`, que lo ejecuta como el usuario del servicio y con `/etc/storageweb/config.json`.

```
storageweb [--config RUTA] <comando> [opciones]
```

## Opciones globales

| Opción | Descripción |
|---|---|
| `--config` `RUTA` | Ruta a config.json (por defecto $STORAGEWEB_CONFIG, luego /etc/storageweb/config.json) |

## Comandos

| Comando | Descripción |
|---|---|
| [`serve`](#serve) | Arranca el servidor web |
| [`service`](#service) | Servicio de Windows: instalar, quitar, arrancar, parar o ver su estado |
| [`init-db`](#init-db) | Crea la base de datos o aplica las migraciones pendientes |
| [`user-add`](#user-add) | Crea un usuario (local por defecto) |
| [`user-passwd`](#user-passwd) | Cambia la contraseña de un usuario local |
| [`user-set`](#user-set) | Modifica rol, grupos, carpeta, idioma o estado de un usuario |
| [`user-del`](#user-del) | Elimina un usuario (no borra sus archivos) |
| [`user-list`](#user-list) | Lista usuarios |
| [`user-exists`](#user-exists) | Código de salida 0 si el usuario existe, 1 si no |
| [`audit`](#audit) | Muestra el registro de auditoría |
| [`check-config`](#check-config) | Valida la configuración y avisa si no hay ningún administrador |
| [`settings-reset`](#settings-reset) | Descartar los ajustes guardados desde la web y volver a los valores predeterminados |
| [`ip-list`](#ip-list) | Lista las direcciones IP bloqueadas y permitidas |
| [`ip-unban`](#ip-unban) | Desbloquea una IP o red (rescate si te has bloqueado) |
| [`ip-allow`](#ip-allow) | Añade una IP o red a la lista blanca (nunca se bloquea) |
| [`sessions-close`](#sessions-close) | Cierra las sesiones abiertas de un usuario (o de todos) |
| [`mfa-reset`](#mfa-reset) | Quitar la verificación en dos pasos de un usuario (perdió el móvil y los códigos de recuperación) |
| [`mfa-status`](#mfa-status) | Listar qué cuentas tienen la verificación en dos pasos |
| [`password-list`](#password-list) | Ver, descargar o cambiar la lista de contraseñas comunes |
| [`backup`](#backup) | Copia de seguridad de la base de datos, config.json y secret_key |
| [`backup-list`](#backup-list) | Lista las copias de seguridad de una carpeta |
| [`restore`](#restore) | Restaura una copia (con el servicio parado) |
| [`encrypt-secret`](#encrypt-secret) | Cifrar un secreto para ponerlo en config.json o en una variable de entorno |
| [`rotate-secrets-key`](#rotate-secrets-key) | Crear una clave nueva para los secretos guardados y volver a cifrarlos (con el servicio parado) |

### `serve` {#serve}

Arranca el servidor web.

```
storageweb serve [--host HOST] [--port PORT] [--dev] [--no-reload]
```

| Argumento | Descripción |
|---|---|
| `--host` `HOST` | Sobrescribe server.host |
| `--port` `PORT` | Sobrescribe server.port |
| `--dev` | Desarrollo: depurador y recarga automática |
| `--no-reload` | Con --dev, sin recarga (para depurar) |

### `service` {#service}

Servicio de Windows: instalar, quitar, arrancar, parar o ver su estado.

```
storageweb service <action> [--name NAME] [--account ACCOUNT]
```

| Argumento | Descripción |
|---|---|
| `action` | install, remove, start, stop o status Valores: `install`, `remove`, `start`, `stop`, `status`. |
| `--name` `NAME` | Nombre del servicio (por defecto StorageWeb) Por defecto: `StorageWeb`. |
| `--account` `ACCOUNT` | Cuenta que lo ejecuta: «virtual» (por defecto: NT SERVICE\<nombre>, con acceso solo a las carpetas que necesita) o LocalSystem (acceso total al equipo) Valores: `virtual`, `LocalSystem`. Por defecto: `virtual`. |

### `init-db` {#init-db}

Crea la base de datos o aplica las migraciones pendientes.

```
storageweb init-db
```


### `user-add` {#user-add}

Crea un usuario (local por defecto).

```
storageweb user-add <username> [--source SOURCE] [--role ROLE] [--password PASSWORD] [--password-stdin] [--name NAME] [--email EMAIL] [--groups GROUPS] [--home HOME]
```

| Argumento | Descripción |
|---|---|
| `username` | Nombre de usuario (para Entra ID, el UPN: juan@contoso.com) |
| `--source` `SOURCE` | Método de inicio de sesión de la cuenta (por defecto, el primero que guarda la contraseña aquí: local). Con los demás, el usuario se da de alta antes y se vincula en su primer inicio de sesión. Valores: `local`, `pam`, `entra`. |
| `--role` `ROLE` | Rol del usuario Valores: `admin`, `user`. Por defecto: `user`. |
| `--password` `PASSWORD` | Contraseña (evítalo: queda en el historial; mejor que la pregunte) |
| `--password-stdin` | Lee la contraseña de la entrada estándar |
| `--name` `NAME` | Nombre visible |
| `--email` `EMAIL` | Correo electrónico |
| `--groups` `GROUPS` | Grupos separados por comas (dan acceso a carpetas compartidas) |
| `--home` `HOME` | Carpeta personal propia (por defecto storage.home_template) |

### `user-passwd` {#user-passwd}

Cambia la contraseña de un usuario local.

```
storageweb user-passwd <username> [--password PASSWORD] [--password-stdin]
```

| Argumento | Descripción |
|---|---|
| `username` | Usuario |
| `--password` `PASSWORD` | Nueva contraseña (si se omite, se pregunta) |
| `--password-stdin` | Lee la contraseña de la entrada estándar |

### `user-set` {#user-set}

Modifica rol, grupos, carpeta, idioma o estado de un usuario.

```
storageweb user-set <username> [--role ROLE] [--groups GROUPS] [--home HOME] [--name NAME] [--email EMAIL] [--locale LOCALE] [--enable] [--disable]
```

| Argumento | Descripción |
|---|---|
| `username` | Usuario |
| `--role` `ROLE` | Nuevo rol Valores: `admin`, `user`. |
| `--groups` `GROUPS` | Grupos separados por comas (sustituye los actuales) |
| `--home` `HOME` | Carpeta personal; '' para volver a storage.home_template |
| `--name` `NAME` | Nombre visible |
| `--email` `EMAIL` | Correo electrónico |
| `--locale` `LOCALE` | Idioma preferido de la interfaz Valores: `en`, `es`. |
| `--enable` | Activa la cuenta |
| `--disable` | Desactiva la cuenta |

### `user-del` {#user-del}

Elimina un usuario (no borra sus archivos).

```
storageweb user-del <username>
```

| Argumento | Descripción |
|---|---|
| `username` | Usuario |

### `user-list` {#user-list}

Lista usuarios.

```
storageweb user-list
```


### `user-exists` {#user-exists}

Código de salida 0 si el usuario existe, 1 si no.

```
storageweb user-exists <username>
```

| Argumento | Descripción |
|---|---|
| `username` | Usuario |

### `audit` {#audit}

Muestra el registro de auditoría.

```
storageweb audit [--limit LIMIT] [--user USER] [--level LEVEL]
```

| Argumento | Descripción |
|---|---|
| `--limit` `LIMIT` | Número máximo de entradas Por defecto: `50`. |
| `--user` `USER` | Filtra por usuario |
| `--level` `LEVEL` | Solo desde este nivel hacia arriba Valores: `debug`, `info`, `warning`, `error`, `critical`. |

### `check-config` {#check-config}

Valida la configuración y avisa si no hay ningún administrador.

```
storageweb check-config
```


### `settings-reset` {#settings-reset}

Descartar los ajustes guardados desde la web y volver a los valores predeterminados.

```
storageweb settings-reset
```


### `ip-list` {#ip-list}

Lista las direcciones IP bloqueadas y permitidas.

```
storageweb ip-list
```


### `ip-unban` {#ip-unban}

Desbloquea una IP o red (rescate si te has bloqueado).

```
storageweb ip-unban <network> [--all]
```

| Argumento | Descripción |
|---|---|
| `network` | Dirección IP o red (CIDR) |
| `--all` | Quitar todos los bloqueos |

### `ip-allow` {#ip-allow}

Añade una IP o red a la lista blanca (nunca se bloquea).

```
storageweb ip-allow <network> [--reason REASON]
```

| Argumento | Descripción |
|---|---|
| `network` | Dirección IP o red (CIDR) |
| `--reason` `REASON` | Nota |

### `sessions-close` {#sessions-close}

Cierra las sesiones abiertas de un usuario (o de todos).

```
storageweb sessions-close <username> [--all]
```

| Argumento | Descripción |
|---|---|
| `username` | Usuario |
| `--all` | Cerrar todas las sesiones |

### `mfa-reset` {#mfa-reset}

Quitar la verificación en dos pasos de un usuario (perdió el móvil y los códigos de recuperación).

```
storageweb mfa-reset <username>
```

| Argumento | Descripción |
|---|---|
| `username` |  |

### `mfa-status` {#mfa-status}

Listar qué cuentas tienen la verificación en dos pasos.

```
storageweb mfa-status
```


### `password-list` {#password-list}

Ver, descargar o cambiar la lista de contraseñas comunes.

```
storageweb password-list [--download] [--file FILE] [--reset] [--url URL]
```

| Argumento | Descripción |
|---|---|
| `--download` | Descargarla de security.password_list_urls (o de --url) como lista propia |
| `--file` `FILE` | Usar este fichero de texto (una contraseña por línea) como lista propia |
| `--reset` | Borrar la lista propia: vuelve a usarse la de serie |
| `--url` `URL` | Dirección de la que descargarla (en lugar del ajuste); se puede repetir |

### `backup` {#backup}

Copia de seguridad de la base de datos, config.json y secret_key.

```
storageweb backup [--output OUTPUT] [--keep KEEP] [--no-offsite]
```

| Argumento | Descripción |
|---|---|
| `--output` `OUTPUT` | Carpeta de destino (por defecto <data_dir>/backups) |
| `--keep` `KEEP` | Conserva solo las N copias más recientes de la carpeta |
| `--no-offsite` | No enviarla fuera del servidor aunque maintenance.offsite_location esté configurado |

### `backup-list` {#backup-list}

Lista las copias de seguridad de una carpeta.

```
storageweb backup-list [--output OUTPUT]
```

| Argumento | Descripción |
|---|---|
| `--output` `OUTPUT` | Carpeta de copias (por defecto <data_dir>/backups) |

### `restore` {#restore}

Restaura una copia (con el servicio parado).

```
storageweb restore <archive> [--force] [--config-to CONFIG_TO]
```

| Argumento | Descripción |
|---|---|
| `archive` | Fichero storageweb-backup-*.tar.gz |
| `--force` | Reemplaza la base de datos existente (antes guarda una copia .antes-de-restaurar-*) |
| `--config-to` `CONFIG_TO` | Escribe el config.json de la copia en esta ruta |

### `encrypt-secret` {#encrypt-secret}

Cifrar un secreto para ponerlo en config.json o en una variable de entorno.

```
storageweb encrypt-secret [--value VALUE]
```

| Argumento | Descripción |
|---|---|
| `--value` `VALUE` | El secreto (si falta, se pide sin mostrarlo) |

### `rotate-secrets-key` {#rotate-secrets-key}

Crear una clave nueva para los secretos guardados y volver a cifrarlos (con el servicio parado).

```
storageweb rotate-secrets-key
```


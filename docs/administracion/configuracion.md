# Configuración

## Capas de configuración

```mermaid
flowchart LR
    D[Valores<br/>predeterminados] --> W[Ajustes web<br/>SQLite] --> F[config.json] --> V[Variables de<br/>entorno] --> E((Configuración<br/>efectiva))
```

Cada valor sale de la capa con más prioridad que lo fije, **campo a campo**:

| Capa | Dónde | Qué | En la web |
|---|---|---|---|
| **Predeterminado** | El propio StorageWeb | Todo | Sin etiqueta |
| **Ajustes web** | Páginas de la administración, guardados en la base de datos | `app_name`, `default_locale`, `branding`, `network`, `storage`, `permissions`, `auth`, `security` y `maintenance` | Etiqueta **modificado** y botón *Restablecer*, que vuelve al predeterminado |
| **`config.json`** | `/etc/storageweb/config.json` (paquetes), `/data/config.json` (Docker) | Todo | El campo queda **bloqueado** (🔒 config.json) |
| **Variable de entorno** | `STORAGEWEB_<RUTA>`, con `__` entre niveles: `STORAGEWEB_AUTH__ENTRA__CLIENT_ID` | Todo | El campo queda **bloqueado** (🔒 entorno, con el nombre de la variable) |

- **Arranque:** `server`, `data_dir`, `database`, `secret_key`, `session` y `settings_profile` solo se configuran en `config.json` o con variables, y requieren reiniciar el servicio: hacen falta antes de abrir la base de datos.
- **Bloqueados:** lo que fijan `config.json` o una variable se ve en la web pero no se puede cambiar ni restablecer. Para editarlo desde la web, quítalo del fichero (o quita la variable) y reinicia. El Resumen avisa de cuántos ajustes están bloqueados.
- **Valores no predeterminados:** el submenú de cada zona cuenta, por página, los ajustes que no tienen su valor predeterminado, vengan de donde vengan. *Sistema → Información* los lista todos con su valor y su origen.
- **Vuelta atrás completa:** *Sistema → Información → Restablecer todos los ajustes web* o `storageweb-admin settings-reset` descartan los ajustes web; lo que fijan `config.json` y el entorno no cambia.
- **Secretos:** el `client_secret` de Entra ID nunca se muestra. Si dejas el campo vacío, se conserva el actual.

*Sistema → Información* empieza por lo que se pregunta primero cuando algo falla:

- **Esta instalación:** la versión, cómo se ejecuta (servicio de Windows, contenedor Docker o Podman, servicio de systemd, servidor de desarrollo o un proceso a mano), cuándo arrancó, el PID y los hilos de Waitress, y el Python que la ejecuta.
- **Servidor:** nombre, sistema operativo y arquitectura, procesadores (y la carga en Linux y macOS), memoria y la **hora del servidor** con su zona: los códigos de la app de verificación dependen de ella.
- **Base de datos:** versión de SQLite, modo del diario, tamaño (y lo que hay en el WAL) y la versión del esquema frente a la que espera esta versión de StorageWeb.
- **Carpetas** donde escribe: datos, carpetas personales, copias, subidas a medias y registros, cada una con si existe, si se puede escribir y el espacio libre (una vez por disco). Las que se crean al hacer falta no salen como un fallo.
- **Cómo ha llegado esta página:** la dirección, la tuya y si *Red y HTTPS* ve algún problema.
- **Componentes:** las bibliotecas que pide StorageWeb con la versión instalada (las que faltan, primero) y las opcionales de cada tipo de ubicación (S3, SMB, SFTP, Azure), y las de JavaScript que viajan con StorageWeb (Mermaid y highlight.js) con su versión y si algún archivo se ha cambiado a mano. Si los datos del paquete instalado son de otra versión que el código, lo avisa (se arregla volviendo a instalarlo).

**Descargar el informe** da todo eso en texto o JSON, sin secretos, para adjuntarlo a una incidencia (`system_report` en la auditoría).

![Sistema → Información: lo de arranque y, campo a campo, de dónde sale cada valor](../img/admin/sistema.webp)

!!! note "¿Cuál uso?"
    - **Desde el navegador:** deja en `config.json` solo lo de arranque (es lo que traen los paquetes y la imagen Docker) y configura lo demás en la web.
    - **Ansible, Puppet, Kubernetes…:** pon en `config.json` o en variables lo que deba ser fijo. La web lo muestra bloqueado y nadie lo cambia por error.

### Variables de entorno

El nombre es `STORAGEWEB_` más la ruta del campo en mayúsculas, con `__` entre niveles. La [referencia de configuración](../referencia/configuracion.md) da el nombre de cada una.

```bash
STORAGEWEB_APP_NAME="Archivos Empresa"
STORAGEWEB_AUTH__ENTRA__ENABLED=true
STORAGEWEB_AUTH__ENTRA__CLIENT_ID=00000000-0000-0000-0000-000000000000
STORAGEWEB_AUTH__PAM__ALLOWED_GROUPS=storageweb-users,contabilidad
STORAGEWEB_STORAGE__SHARES='[{"name": "comun", "path": "/srv/comun", "users": ["*"]}]'
```

- **Booleanos:** `true`/`false` (también `1`/`0`, `yes`/`no`, `on`/`off`).
- **Listas y objetos:** JSON. Las listas de texto también se pueden separar por comas.
- **Nombres cortos:** se mantienen `STORAGEWEB_PUBLIC_URL`, `STORAGEWEB_PORT`, `STORAGEWEB_BEHIND_PROXY`, `STORAGEWEB_PROXY_HOPS`, `STORAGEWEB_MAX_UPLOAD_MB` y `STORAGEWEB_COOKIE_SECURE`.
- Un valor no válido impide arrancar, con un error que nombra la variable.

### Varias configuraciones en una base de datos

`settings_profile` (o `STORAGEWEB_SETTINGS_PROFILE`) elige el **perfil** de ajustes web que usa la instancia. Por defecto es `default`. Varias instancias pueden compartir base de datos con ajustes distintos, igual que si cada una tuviera su `config.json`: por ejemplo, una de pruebas y otra de producción. Lo demás de la base de datos (usuarios, grupos, sesiones, auditoría) es común. `settings-reset` solo descarta el perfil de la instancia. *Sistema → Información* muestra el perfil activo, los demás perfiles de la base de datos y quién y cuándo cambió cada ajuste. Si las instancias comparten base de datos, que compartan también la [clave de los secretos](seguridad.md#secretos-guardados) (`STORAGEWEB_SECRETS_KEY` o el mismo `secrets.key`): al restaurar una copia se vuelven a cifrar los secretos de todos los perfiles con la clave de quien restaura.

## La administración

La barra lateral tiene *Archivos* y, para los administradores, el **Resumen** y cuatro zonas. Cada zona tiene un submenú a la izquierda (arriba en pantallas estrechas):

| Zona | Páginas |
|---|---|
| **Resumen** | Avisos que necesitan atención (secreto de Entra ID a punto de caducar, carpetas que no existen, copias automáticas que no se hacen, problemas de red), una tarjeta por zona, tareas frecuentes y la actividad reciente. El número rojo de la barra lateral cuenta los avisos |
| **Personas** | Usuarios · Grupos · Sesiones y tokens |
| **Acceso** | Carpetas compartidas · Matriz de accesos · Permisos del rol · Carpetas personales · Cuotas |
| **Seguridad** | Estado de la seguridad · Vulnerabilidades · Inicio de sesión · Reglas de bloqueo · API y unidad de red · IPs bloqueadas · Auditoría · Registro de auditoría (retención, niveles y SIEM) |
| **Sistema** | General y marca · Red y HTTPS · Almacenamiento externo · Archivos y explorador · Vista previa · Copias automáticas · Copias y base de datos · Monitorización · Información |

**Ajustes bloqueados:** lo que está en `config.json` o en una variable de entorno no se cambia desde la web. En el menú de cada zona, junto a la página, un candado dice cuántos ajustes suyos están así; arriba de la página, la lista de esos ajustes (con su variable de entorno o `config.json`) enlaza a cada uno, y el campo sale desactivado con su origen.

Cada página dice de qué tipo es:

- **Configuración · se aplica al guardar:** un formulario. La barra de guardar aparece al cambiar algo y dice cuántos cambios hay; el navegador avisa si sales sin guardar. Si un valor no es válido, el error sale junto al campo y no se guarda nada.
- **Operación · se aplica al momento:** acciones que se hacen al pulsar (cerrar sesiones, bloquear una IP, crear una copia…).
- **Solo lectura:** *Información* y *Auditoría*.

Las direcciones de las secciones de ajustes no cambian (`/admin/settings/auth`, `/admin/settings/ips`…); `/admin/settings/shares` redirige a *Acceso → Carpetas compartidas*.

![El Resumen: avisos, una tarjeta por zona, tareas frecuentes y la actividad reciente](../img/admin/resumen.webp)

### Buscador

**Ctrl+K** (o la tecla `/`) abre el buscador desde cualquier página. Encuentra páginas, ajustes, acciones frecuentes, usuarios, grupos y carpetas compartidas, sin distinguir mayúsculas ni tildes. Un ajuste lleva a su página, abre la pestaña que lo contiene y resalta el campo. Sin JavaScript, el cuadro del Resumen lleva a una página de resultados (`/admin/search?q=…`).

![El buscador (Ctrl+K) con los ajustes de cuotas](../img/admin/buscador.webp)

### Carpetas compartidas

*Acceso → Carpetas compartidas* muestra cada carpeta con quién entra y con qué permiso, y avisa si la ruta no existe en el servidor. En la ficha de cada carpeta se cambian el nombre, la etiqueta, la ruta y *Solo lectura para todos*, y se da o se quita el acceso a **todos los usuarios**, a un **usuario** o a un **grupo**, cada uno con *Lectura y escritura* o *Solo lectura*. Quitar una carpeta no borra sus archivos. La *Matriz de accesos* es la misma información vista por grupos.

![Acceso → Carpetas compartidas: cada carpeta con quién entra y con qué permiso](../img/admin/carpetas.webp)

![La ficha de una carpeta: ruta, cuota y quién entra](../img/admin/carpeta.webp)

### Marca

*Sistema → General y marca* tiene el nombre de la aplicación y el idioma por defecto, el **color principal**, el **logo** (sustituye al cubo de serie en la barra lateral, el inicio de sesión y la pestaña del navegador) y la **imagen del inicio de sesión**: una de las cinco ilustraciones de serie, que toman el color principal, *Aleatoria* para una distinta en cada carga, o una foto propia que se sube ahí mismo.

![Sistema → General y marca: aplicación, color principal, logo e imagen del inicio de sesión](../img/admin/marca.webp)

## Dónde se busca `config.json`

Por este orden:

1. `--config RUTA`;
2. la variable `STORAGEWEB_CONFIG`;
3. `/etc/storageweb/config.json`, si existe (Linux y macOS);
4. `./config/config.json` en el directorio actual.

Las **rutas relativas** del fichero se resuelven respecto a la carpeta donde está el propio `config.json`.

## Validar

```bash
sudo storageweb-admin check-config
```

El comando muestra:

- las rutas efectivas;
- los métodos de inicio de sesión activos;
- si cada carpeta compartida existe;
- un aviso si no hay ningún administrador.

## Ejemplos

### Idioma

```json
"default_locale": "en"
```

La interfaz y la CLI están en inglés (`en`, por defecto) y español (`es`). El idioma de cada petición se elige por este orden:

1. la preferencia del usuario, guardada al pulsar ES/EN (o con `storageweb-admin user-set <usuario> --locale en`);
2. el idioma elegido en la sesión;
3. el `Accept-Language` del navegador;
4. `default_locale`.

La CLI usa `STORAGEWEB_LANG`, o `LC_ALL`/`LANG` (por ejemplo `STORAGEWEB_LANG=en storageweb-admin check-config`). Los logs siempre están en inglés.

### Carpetas compartidas

```json
"storage": {
  "home_template": "/srv/storageweb/homes/{username}",
  "max_file_size_mb": 0,
  "shares": [
    {"name": "comun", "label": "Común", "path": "/srv/storageweb/shared", "users": ["*"]},
    {"name": "rrhh", "label": "RR. HH.", "path": "/srv/rrhh", "groups": ["rrhh"]},
    {"name": "manuales", "label": "Manuales", "path": "/srv/manuales", "read_only": true, "users": ["*"]}
  ]
}
```

El acceso se concede si el usuario aparece en `users` (`*` = todos) **o** pertenece a uno de los `groups`. Cada vía puede ser de solo lectura: `read_only_users` (usuarios de `users`, o `*`) y `read_only_groups` (grupos de `groups`). Se puede escribir si **alguna** de las vías por las que entra el usuario lo permite; `read_only: true` deja la carpeta en solo lectura para todos.

```json
{"name": "software", "path": "/srv/software", "users": ["*", "ana"], "read_only_users": ["*"],
 "groups": ["sistemas"]}
```

Aquí todos leen, y `ana` y el grupo `sistemas` además escriben. Las rutas deben existir y ser accesibles para el usuario del servicio, salvo que actives `create_shares`.

### Permisos del rol `user`

```json
"permissions": {"user": {"upload": true, "download": true, "mkdir": true, "rename": true, "delete": false}}
```

### Límites

```json
"server":  {"max_upload_mb": 2048},
"storage": {"max_file_size_mb": 10240},
"security": {"max_login_failures": 5, "lockout_minutes": 15}
```

`server.max_upload_mb` limita cada **petición** (y requiere reinicio). `storage.max_file_size_mb` limita cada **archivo**.

La lista completa de opciones está en la [referencia de configuración](../referencia/configuracion.md).

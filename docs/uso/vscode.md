# Extensión de Visual Studio Code

La extensión **StorageWeb** añade a VS Code un panel propio en la barra lateral (como *Extensiones* o *Ejecutar y depurar*) desde el que:

- **Navegas por tus servidores** de StorageWeb (los que quieras, cada uno con su usuario): tu carpeta personal y las compartidas.
- **Abres y guardas archivos directamente en el servidor**, sin copiarlos a tu equipo, y subes, bajas, renombras o borras.
- **Sincronizas** una carpeta de tu equipo con una del servidor, en los dos sentidos: lo que guardas se sube al momento y lo que cambia en el servidor (otra persona, otro equipo, la web) te llega solo.

Está en `clients/vscode/` del repositorio. No hay que compilar nada: es JavaScript sin dependencias.

## Instalarla

Necesita VS Code 1.85 o posterior y que StorageWeb tenga activada la [unidad de red (WebDAV)](unidad-de-red.md), que viene así por defecto. No hay que compilar nada: la extensión está en JavaScript y no tiene dependencias.

### 1. Conseguir el fichero `.vsix`

- **De una versión publicada:** en la *release* de GitHub, el fichero `storageweb-sync-X.Y.Z.vsix` (tiene la misma versión que StorageWeb).
- **De la última versión en desarrollo:** en GitHub, *Actions → CI →* la última ejecución de la rama principal → artefacto **storageweb-vscode** (es un `.zip` con el `.vsix` dentro).
- **Generarlo** desde el repositorio:
  ```bash
  python tools/build_vsix.py
  ```
  Crea `clients/vscode/dist/storageweb-sync-<versión>.vsix`; con `--install` lo instala además en VS Code (con la orden `code`). También está la tarea de VS Code *StorageWeb: empaquetar la extensión de VS Code* (*Terminal → Ejecutar tarea…*), que pregunta si instalarla al terminar.

### 2. Instalarlo en VS Code

- **Desde VS Code:** *Extensiones* (`Ctrl+Shift+X`) → `⋯` (arriba a la derecha) → **Instalar desde VSIX…** → elige el fichero.
- **Desde la consola:**
  ```bash
  code --install-extension storageweb-sync-0.4.0.vsix
  ```

Si VS Code ya estaba abierto al instalar desde la consola, **recarga la ventana** para que la cargue: `Ctrl+Shift+P` → *Developer: Reload Window* (*Desarrollador: Recargar ventana*), o el botón *Recargar* que aparece junto a la extensión. No hace falta cerrar VS Code. Al instalar desde la interfaz suele activarse sola; si no ves el icono de StorageWeb (una nube con una flecha) en la barra de actividad de la izquierda, recarga igual.

!!! warning "No hagas doble clic en el `.vsix`"
    En Windows, si tienes Visual Studio (el IDE, no VS Code) instalado, el doble clic abre el *Instalador de VSIX* de Visual Studio, que responde «Una o varias extensiones son para Visual Studio Code. Intente instalarlas en Visual Studio Code». El fichero está bien: instálalo con uno de los dos métodos de arriba.

Para **actualizarla**, instala el `.vsix` nuevo de la misma forma y recarga la ventana: sustituye al anterior y conserva la vinculación y el token. Para **quitarla**: *Extensiones* → StorageWeb → *Desinstalar* (no borra nada ni aquí ni en el servidor).

## El panel de StorageWeb

Pulsa el icono de StorageWeb en la barra de actividad (a la izquierda). Tiene dos secciones:

- **Servidores**: los servidores que has añadido y, dentro de cada uno, tu carpeta personal (`home`) y las compartidas a las que tienes acceso, para ir abriendo carpetas.
- **Sincronización**: las carpetas de esta ventana que se sincronizan, con su estado (sincronizado, sincronizando, error o sin token). Con clic derecho: *Sincronizar ahora*, *Abrir en el navegador*, *Ver el registro* y *Desvincular*.

### Añadir un servidor

En el panel, sección *Servidores*, botón **+** (*Añadir servidor…*). Escribe la dirección de StorageWeb (`https://archivos.empresa.es`) y elige cómo entrar:

- **Iniciar sesión en el navegador** (recomendado). Se abre StorageWeb en tu navegador; entras como siempre (con Microsoft si tu StorageWeb usa Entra ID: en un equipo unido a Entra ID y con `auth.entra.auto_login`, sin escribir nada) y la página pregunta si permites conectar *Visual Studio Code* desde ese equipo, con qué alcance y hasta cuándo. Al pulsar **Permitir**, el navegador vuelve a VS Code (puede preguntar si abrir Visual Studio Code: acepta) y ya está: no hay que copiar nada. Se crea un token llamado «Visual Studio Code (*nombre del equipo*)», que ves y puedes revocar en *Mi perfil → Tokens de API*.
- **Usuario y token de API**, como antes: crea el token en StorageWeb, *Mi perfil → Tokens de API*, con alcance **lectura y escritura** (o **solo lectura** si solo vas a mirar y descargar), y escribe tu usuario y el token.

En los dos casos la extensión comprueba que funcionan antes de guardarlo. *Cambiar el token…* pregunta lo mismo; con el navegador tienes que entrar con el mismo usuario del servidor (otra cuenta es otro servidor).

!!! note "Iniciar sesión en el navegador"
    Necesita que StorageWeb tenga los tokens de API activados (*Seguridad → Reglas de bloqueo*, vienen así) y un servidor con esta versión o posterior; si no, la extensión lo dice y puedes usar usuario y token. No funciona en VS Code en el navegador (vscode.dev) ni en conexiones remotas. El intercambio es seguro aunque otro programa vea la vuelta a VS Code: el código solo vale una vez, durante 5 minutos, y solo con un secreto que la extensión nunca envía al navegador (PKCE).

Puedes añadir varios: servidores distintos, o el mismo con otra cuenta. Con clic derecho sobre un servidor: *Editar servidor…* (el nombre que se ve o la dirección), *Cambiar el token…*, *Abrir en el navegador* y *Quitar servidor* (borra su token de este equipo; en el servidor no se borra nada). Si el servidor rechaza el token (lo revocaste o caducó), el panel lo dice y ofrece ponerlo otra vez.

### Trabajar con los archivos del servidor

- **Abrir:** clic en un archivo. Se abre en VS Code directamente desde el servidor y, al guardar (`Ctrl+S`), se guarda en el servidor.
- **Clic derecho sobre una carpeta:** *Nueva carpeta…*, *Subir archivos…*, *Subir carpeta…*, *Descargar…* (la carpeta entera), *Renombrar…*, *Borrar*, *Abrir en el navegador*, *Sincronizar con una carpeta local…* y *Añadir al espacio de trabajo*. Subir y crear carpetas también están como botones al pasar el ratón.
- **Clic derecho sobre un archivo:** *Abrir*, *Descargar…*, *Renombrar…*, *Borrar* y *Abrir en el navegador*.
- **Añadir al espacio de trabajo:** la carpeta del servidor aparece en el *Explorador* de VS Code junto a las tuyas, con lo habitual: abrir, guardar, crear, renombrar, arrastrar para copiar… Los archivos no se copian a tu equipo: cada operación va al servidor.

Al guardar **no se pisan cambios ajenos**: si el archivo cambió en el servidor desde que lo abriste, VS Code avisa y te deja comparar o sobrescribir; y si cambia justo mientras se guarda, el servidor rechaza la escritura (`If-Match`) y te pide que lo vuelvas a abrir. Borrar en el servidor **no se puede deshacer** (StorageWeb no tiene papelera): la extensión pregunta antes.

Los cambios que hagan otros no aparecen solos en el panel: pulsa *Actualizar* (el botón de la sección o el de cada carpeta).

## Sincronizar una carpeta

Hay dos formas:

- **Desde el panel:** clic derecho sobre una carpeta del servidor → **Sincronizar con una carpeta local…** y elige la carpeta de tu equipo. Si no está abierta en VS Code, la extensión ofrece abrirla (aquí, en otra ventana o añadiéndola al espacio de trabajo) y la vincula al abrirse.
- **Con la carpeta ya abierta:** en la sección *Sincronización*, el botón de enlace, o `Ctrl+Shift+P` → **StorageWeb: Sincronizar una carpeta de esta ventana…**. Eliges el servidor (o añades uno; si no tiene token en este equipo, pregunta cómo entrar) y navegas hasta la carpeta del servidor (o creas una con *Nueva carpeta aquí…*).

La primera sincronización junta las dos carpetas: sube lo que solo está en tu equipo, baja lo que solo está en el servidor y, si un archivo está en los dos, compara el contenido. Si es igual, no hace nada; si no, guarda las dos versiones (ver *Conflictos*). No borra nada.

El icono de la nube de la barra de estado resume el estado de todas (sincronizado, sincronizando o error). Al pulsarlo aparecen *Sincronizar ahora*, *Abrir en el navegador*, *Ver el registro* y *Desvincular*.

## Cómo sincroniza

- **Al guardar**, crear, renombrar o borrar un archivo, sube o borra solo ese archivo (a los 1,5 s, juntando los cambios seguidos).
- **Cada minuto** (`storageweb.pollSeconds`), una sincronización completa trae lo que cambió en el servidor.
- **Nunca pisa cambios ajenos.** Cada subida dice qué versión del archivo conocía (`If-Match`): si alguien lo cambió en el servidor entre medias, StorageWeb la rechaza y la extensión lo trata como conflicto.
- **Conflictos:** si un archivo cambió aquí y en el servidor, la versión del servidor se queda con el nombre original y la tuya pasa a `nombre (conflicto AAAA-MM-DD HHMM).ext`, que también se sube. Un aviso ofrece **Comparar** las dos con la vista de diferencias de VS Code. Nunca se pierde nada.
- **Borrados:** lo que se borra en tu equipo porque se borró en el servidor va a la **papelera**. Si una sincronización fuera a borrar más de `storageweb.confirmDeletesOver` archivos de golpe (por ejemplo, porque se vació una carpeta por error), pregunta antes; si dices que no, los recupera del lado que todavía los tiene.
- **Sin acumular:** si una sincronización completa tarda mucho (la primera de una carpeta grande), la siguiente espera al menos el triple de lo que tardó, y nunca se ponen varias en cola. Una pasada larga guarda lo hecho por el camino: si se corta, la siguiente sigue donde iba.
- **Protección contra bucles:** antes de la primera sincronización, la extensión deja un archivo de prueba en la carpeta del servidor y mira si aparece en tu carpeta. Si aparece, tu carpeta contiene el sitio donde el servidor guarda esos archivos (por ejemplo, un StorageWeb de pruebas que guarda sus datos dentro del proyecto que sincronizas): cada subida volvería a aparecer dentro, sin fin. No sincroniza nada y ofrece **excluir esa carpeta** o desvincular.

## Qué no se sincroniza

- **Siempre:** `.git`, `.svn`, `.hg`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `*.pyc`, los temporales de Office y del sistema, y `.vscode/settings.json` (donde está la vinculación).
- **Lo que ignora el `.gitignore`** de la raíz de la carpeta (ajuste `storageweb.useGitignore`, activado por defecto).
- **Lo que pongas en `.storagewebignore`**, en la raíz de la carpeta, con el formato de `.gitignore`:
  ```gitignore
  # Comentario
  /.dev/          # esa carpeta, solo en la raíz
  dist/           # cualquier carpeta «dist»
  *.log           # por extensión, en cualquier sitio
  docs/borradores/*.bak
  ```
  Este fichero **también se sincroniza**, así que vale para todos los equipos que usen la carpeta. Las líneas con `!` (excepciones) no se admiten: se ignoran y se avisa en el registro.
- **Lo que pongas en `storageweb.exclude`** (ajustes de VS Code), solo en este equipo: por ejemplo `["dist/**", "**/*.log"]`.
- **Lo que el administrador oculta en el servidor** (`storage.hidden`, ver [Almacenamiento](../administracion/almacenamiento.md#ocultar-archivos-para-todos)): si tienes un archivo así en tu carpeta, el servidor no lo acepta. La extensión lo apunta, **no lo sube ni lo borra de tu equipo**, y lo vuelve a probar una vez al día (por si deja de estar oculto). El registro dice cuántos hay.

Lo más rápido: en el *Explorador*, clic derecho sobre un archivo o carpeta → **No sincronizar**. Lo añade al `.storagewebignore` (creándolo si no existe). En el panel *Sincronización*, clic derecho → **Editar exclusiones (.storagewebignore)** lo abre. Al guardarlo, la sincronización vuelve a empezar con las exclusiones nuevas. Lo que ya estaba en el servidor **se queda allí**: excluir no borra nada, ni aquí ni allí.

## Pausar

En el panel *Sincronización*, el botón de pausa de cada carpeta (o el de arriba, para todas), o el icono de la barra de estado → **Pausar la sincronización**. Para en el acto la pasada que esté en marcha, deja de vigilar tus cambios y de consultar el servidor. La pausa se mantiene aunque cierres o recargues VS Code, hasta que pulses **Reanudar** (o *Sincronizar ahora* sobre esa carpeta). Al reanudar se hace una sincronización completa con lo que haya cambiado en los dos lados mientras tanto.

## Ajustes

| Ajuste | Por defecto | |
|---|---|---|
| `storageweb.server`, `storageweb.username`, `storageweb.remoteFolder` | | Los pone *Sincronizar*, en los ajustes de la carpeta (`.vscode/settings.json`) |
| `storageweb.autoSync` | `true` | Subir al guardar, crear, renombrar o borrar |
| `storageweb.pollSeconds` | `60` | Segundos entre sincronizaciones completas (mínimo 15) |
| `storageweb.exclude` | `[]` | Más patrones que no se sincronizan, solo en este equipo |
| `storageweb.useGitignore` | `true` | No sincronizar lo que ignora el `.gitignore` de la raíz de la carpeta |
| `storageweb.confirmDeletesOver` | `10` | Preguntar antes de borrar más de estos archivos de una vez |

La **lista de servidores** se guarda en este equipo (en los datos de la extensión, no en los ajustes) y el **token** de cada uno en el almacén de secretos de VS Code (el del sistema operativo), nunca en los ajustes ni en el proyecto. *Quitar servidor* o *StorageWeb: Olvidar el token* lo quitan de este equipo; para anularlo del todo, revócalo en *Mi perfil*. Las carpetas que ya sincronizabas con la versión 0.1 aparecen solas en *Servidores*.

## Seguridad

- Usa la unidad de red de StorageWeb (`/dav/`) con los mismos permisos que la web. Con un token de solo lectura, los cambios no se suben.
- Solo funciona en espacios de trabajo de confianza (VS Code pregunta al abrir una carpeta desconocida).
- Lo que sube y baja queda en la [auditoría](../referencia/auditoria.md) con el detalle `webdav`.

## Limitaciones

- Las carpetas vacías no se sincronizan, solo los archivos.
- Abrir archivos del servidor sin sincronizar necesita conexión: sin red no se abren ni se guardan. La búsqueda de VS Code (`Ctrl+Shift+F`) no busca dentro de las carpetas del servidor añadidas al espacio de trabajo.
- El panel no se entera solo de los cambios que hacen otros: *Actualizar*.
- Cada archivo, como mucho `server.max_upload_mb` del servidor.
- La sincronización completa recorre toda la carpeta (una consulta al servidor por cada subcarpeta): con muchos miles de archivos, excluye lo que no haga falta o sube `storageweb.pollSeconds`. No sincronices carpetas enteras de dependencias o compilados.
- Entrar con la sesión de Windows sin pasar por el navegador (Entra ID, WAM) está en la [hoja de ruta](../proyecto/hoja-de-ruta.md); mientras tanto, *Iniciar sesión en el navegador* ya usa el inicio de sesión de Microsoft.

## Para desarrolladores

```bash
node --test clients/vscode/test      # tests de la extensión (Node 18 o posterior)
python tools/build_vsix.py --install # empaqueta e instala en este VS Code (luego, recargar la ventana)
```

La lógica está en módulos sin VS Code que se prueban con Node:

| Módulo | |
|---|---|
| `src/sync.js` | Motor de sincronización: tres vías, conflictos, comprobación de bucle, cancelar, rutas ocultas en el servidor |
| `src/dav.js` | Cliente WebDAV |
| `src/remotefs.js` | Los archivos de un servidor como sistema de archivos |
| `src/servers.js` | Lista de servidores (tokens en el almacén de secretos) |
| `src/connect.js` | Iniciar sesión en el navegador (PKCE, [ADR 0016](../arquitectura/decisiones/0016-conectar-aplicaciones-con-el-navegador.md)) |
| `src/glob.js`, `src/localfs.js` | Exclusiones (`.storagewebignore`, `.gitignore`) y disco local |

`src/provider.js` y `src/views.js` los adaptan a la API de VS Code (`storageweb://` y los paneles) y `src/extension.js` añade comandos, avisos, pausa y la vigilancia de cambios.

Pruebas:
- `test/extension.test.js` carga la extensión con un `vscode` simulado (`test/vscode-mock.js`) y comprueba que cada comando del `package.json` existe.
- `test/robust.test.js` cubre los casos que salieron usándola: archivos que el servidor no lista, bucles, cancelar, exclusiones y archivos ocultos.
- `tests/integration/test_vscode_extension.py` arranca un StorageWeb de verdad (con `storage.hidden`) y ejecuta todo contra él, sin omitir nada:
  - **dos equipos** sincronizando la misma carpeta;
  - los paneles y `storageweb://`;
  - el bucle;
  - iniciar sesión en el navegador, con un «navegador» de prueba (`test/browser.js`).
- Se omite si no hay Node.

Cada cambio que quieras instalar necesita **subir la versión** en `package.json`: VS Code no recarga un `.vsix` reinstalado con la misma versión. No se usa npm: si alguna vez hiciera falta una dependencia, con pnpm.

# StorageWeb para VS Code

Un panel propio en la barra lateral de VS Code para tus servidores de StorageWeb:

- **Servidores:** varios, cada uno con su usuario y su token. Navega por tu carpeta personal y las compartidas; abre y guarda archivos **directamente en el servidor**; sube, descarga, renombra y borra; añade una carpeta del servidor al espacio de trabajo.
- **Sincronización:** mantiene una carpeta de tu equipo **sincronizada** con una de StorageWeb, en los dos sentidos.

Al sincronizar:

- **Al guardar**, crear, renombrar o borrar un archivo, sube o borra solo ese archivo.
- **Cada minuto** (configurable), trae lo que haya cambiado en el servidor (otra persona, otro equipo, la web).
- **Nunca pisa cambios ajenos:** cada subida dice qué versión conocía (`If-Match`). Si el archivo cambió en el servidor entre medias, se guardan **las dos versiones**: la del servidor con el nombre original y la tuya como `nombre (conflicto AAAA-MM-DD HHMM).ext`, con un botón para compararlas.
- **Borrados con red de seguridad:** lo que borra la extensión en tu equipo va a la papelera, y si una sincronización fuera a borrar muchos archivos de golpe, pregunta antes. Si dices que no, los recupera.
- No sincroniza `.git`, `node_modules`, `.venv`, `__pycache__`, temporales ni `.vscode/settings.json`, ni lo que ignore el `.gitignore`. Más en `.storagewebignore` (formato de `.gitignore`, se sincroniza) o con clic derecho → *No sincronizar* en el Explorador.
- **Pausar y reanudar** desde el panel *Sincronización* o la barra de estado.
- **Protección contra bucles:** no sincroniza una carpeta que contiene donde el servidor guarda la carpeta remota.
- **Avisos claros** cuando el servidor deniega algo (cuenta desactivada, token caducado, carpeta de solo lectura o a la que ya no tienes acceso, IP bloqueada, mantenimiento, archivo demasiado grande), una vez y sin borrar nada en tu equipo.

## Requisitos

- StorageWeb con la **unidad de red (WebDAV)** activada (*Seguridad → Reglas de bloqueo*), que viene así por defecto.
- Un **token de API** con alcance de lectura y escritura: *StorageWeb → Mi perfil → Tokens de API*.
- VS Code 1.85 o posterior.

## Instalación

1. Consigue el `.vsix`: de la *release* de GitHub (`storageweb-sync-X.Y.Z.vsix`), del artefacto **storageweb-vscode** de la CI, o generándolo:
   ```bash
   python tools/build_vsix.py            # clients/vscode/dist/storageweb-sync-<versión>.vsix
   python tools/build_vsix.py --install  # y además lo instala en VS Code
   ```
2. En VS Code: *Extensiones* (`Ctrl+Shift+X`) → `⋯` → **Instalar desde VSIX…** → elige el fichero. O en la consola: `code --install-extension storageweb-sync-0.4.0.vsix`; si VS Code ya estaba abierto, recarga la ventana (`Ctrl+Shift+P` → *Developer: Reload Window*).

**No hagas doble clic en el `.vsix`:** en Windows con Visual Studio instalado lo abre el instalador de Visual Studio, que dice que la extensión es para VS Code. El fichero está bien; instálalo como en el paso 2.

No hay que compilar nada: la extensión está en JavaScript y no tiene dependencias. Para actualizarla, instala el `.vsix` nuevo igual y recarga la ventana (conserva la vinculación y el token).

## Uso

1. Pulsa el icono de StorageWeb en la barra de actividad (a la izquierda).
2. *Servidores* → **+**: dirección de StorageWeb y cómo entrar: **Iniciar sesión en el navegador** (también con Microsoft / Entra ID; no hay que copiar nada) o **usuario y token de API**.
3. Navega por las carpetas. Clic en un archivo para abrirlo; clic derecho para subir, descargar, renombrar, borrar, **Sincronizar con una carpeta local…** o **Añadir al espacio de trabajo**.
4. O, con la carpeta del proyecto abierta: `Ctrl+Shift+P` → **StorageWeb: Sincronizar una carpeta de esta ventana…** y elige servidor y carpeta.

Desde entonces, el icono de la nube en la barra de estado indica si está sincronizado. Al pulsarlo aparecen *Sincronizar ahora*, *Abrir en el navegador*, *Ver el registro* y *Desvincular*.

| Comando | |
|---|---|
| StorageWeb: Añadir servidor… | Dirección y cómo entrar: navegador, o usuario y token (se comprueban) |
| StorageWeb: Sincronizar una carpeta de esta ventana… | Elige servidor y carpeta del servidor |
| StorageWeb: Sincronizar ahora | Sincronización completa |
| StorageWeb: Abrir en el navegador | La carpeta del archivo abierto, en la web |
| StorageWeb: Ver el registro | Qué se ha subido, bajado o borrado |
| StorageWeb: Desvincular carpeta | Deja de sincronizar (no borra nada) |
| StorageWeb: Olvidar el token | Quita el token de este equipo |

## Ajustes

| Ajuste | Por defecto | |
|---|---|---|
| `storageweb.server`, `storageweb.username`, `storageweb.remoteFolder` | | Los pone *Sincronizar* (en `.vscode/settings.json`) |
| `storageweb.autoSync` | `true` | Subir al guardar, crear, renombrar o borrar |
| `storageweb.pollSeconds` | `60` | Segundos entre sincronizaciones completas |
| `storageweb.exclude` | `[]` | Más patrones que no se sincronizan (`dist/**`, `*.log`) |
| `storageweb.confirmDeletesOver` | `10` | Preguntar antes de borrar más de estos archivos de una vez |

El token se guarda en el almacén de secretos de VS Code (el del sistema), nunca en los ajustes ni en el proyecto.

## Limitaciones

- Las carpetas vacías no se sincronizan (solo los archivos).
- Cada archivo, como mucho `server.max_upload_mb` del servidor.
- Las sincronizaciones completas recorren toda la carpeta: con muchos miles de archivos, sube `storageweb.pollSeconds`.
- Entrar sin token con la sesión de Windows (Entra ID) está en la hoja de ruta de StorageWeb.

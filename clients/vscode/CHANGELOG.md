# Cambios

## 0.4.0

- **Pausar y reanudar** la sincronización de cada carpeta o de todas (panel *Sincronización* y barra de estado). Para la pasada en curso y se mantiene al recargar VS Code.
- **Exclusiones:** fichero `.storagewebignore` en la carpeta (formato de `.gitignore`, se sincroniza), se respeta el `.gitignore` (`storageweb.useGitignore`), *No sincronizar* en el menú del Explorador, y `.venv`, `venv`, `__pycache__`, `*.pyc` y las cachés de Python excluidos siempre.
- **Protección contra bucles:** si la carpeta local contiene donde el servidor guarda la carpeta remota (un StorageWeb de pruebas dentro del proyecto), no sincroniza y ofrece excluirla. Antes, cada subida aparecía otra vez dentro de la carpeta, sin fin.
- Lo que el servidor oculta para todos (`storage.hidden`) se queda solo en el equipo: ni se sube ni se borra, y se vuelve a probar una vez al día.
- Lo que el servidor tiene pero no listaba (archivos que empiezan por punto) ya no se da por borrado: se compara en vez de pedir borrarlo y fallar con 412.
- Las sincronizaciones completas ya no se acumulan (la siguiente espera el triple de lo que tardó la anterior), se guardan por el camino y se paran de verdad al desvincular o pausar.

## 0.3.0

- **Iniciar sesión en el navegador** al añadir un servidor o cambiar el token (también con Microsoft / Entra ID): la extensión recibe un token para el equipo sin copiar nada (OAuth con PKCE). Usuario y token a mano sigue disponible: la extensión pregunta cuál usar.

## 0.2.0

- **Panel propio en la barra lateral** con dos secciones: *Servidores* (varios, cada uno con su usuario y su token en el almacén de secretos) y *Sincronización* (las carpetas sincronizadas y su estado).
- Navegar por las carpetas del servidor y **abrir y guardar archivos directamente en él** (`storageweb://`, con `If-Match` al guardar); nueva carpeta, subir archivos o carpetas, descargar, renombrar, borrar y abrir en el navegador.
- **Añadir una carpeta del servidor al espacio de trabajo** (aparece en el Explorador) y **sincronizar una carpeta del servidor con una local** desde el menú contextual.
- *Vincular carpeta* pasa a *Sincronizar una carpeta de esta ventana…* y elige entre los servidores añadidos. Las carpetas vinculadas con la 0.1 aparecen solas en *Servidores*.

## 0.1.0

- Primera versión: vincular una carpeta, sincronización en los dos sentidos (al guardar y periódica), conflictos con las dos versiones, borrados a la papelera con confirmación de borrados masivos, abrir en el navegador. Inglés y español.

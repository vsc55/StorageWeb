# Cambios

## 0.7.0

- **Entrar con la cuenta de Windows** (equipos unidos a Microsoft Entra ID), sin navegador: si el servidor lo anuncia (`GET /connect/desktop`), al añadir un servidor, en *Cambiar el token…* y en *Iniciar sesión otra vez* la primera opción es *Entrar con tu cuenta de Windows (Microsoft Entra ID)*. VS Code pide a Windows un token de Microsoft para StorageWeb (la primera vez Windows enseña su selector de cuenta; después, nada) y StorageWeb lo canjea por un token de API para el equipo. Si no sale, se dice por qué (lo que explica el servidor) y se ofrecen las otras formas, también *Entrar con otra cuenta de Windows* si la usada no vale. Solo con servidores `https://` (o el propio equipo); lo que se pide a Microsoft es siempre y solo `api://<id>/access_as_user` (un servidor no puede pedir otro permiso ni otra aplicación de VS Code) y se recuerda por servidor: si cambia, se pregunta antes.

## 0.6.0

- **Avisos claros cuando el servidor deniega algo**, con el motivo que da StorageWeb (cabecera `X-StorageWeb-Reason`): cuenta desactivada, token caducado o revocado (con *Iniciar sesión otra vez* y *Cambiar el token…*), tokens desactivados en el servidor, verificación en dos pasos, demasiados intentos fallidos (espera 5 minutos y lo vuelve a intentar sola), IP bloqueada, servidor en mantenimiento (sin aviso: lo vuelve a intentar en la próxima vuelta) y archivos demasiado grandes. Cada aviso sale una vez, no en cada vuelta. Los mismos textos en el panel *Servidores* y al abrir o guardar archivos `storageweb://`.
- **Carpeta del servidor que ya no está o a la que ya no hay acceso:** la sincronización queda en pausa sin borrar nada en el equipo, con *Sincronizar ahora* y *Desvincular*. Al subir, ya no se vuelve a crear la carpeta vinculada si ha desaparecido.
- **Carpeta o token de solo lectura, o rol sin permiso para subir:** avisa una vez de que los cambios no se pueden subir, no intenta el resto de subidas de la pasada y sigue bajando lo que cambie en el servidor. Lo modificado que no se pudo subir se queda en el equipo; lo borrado en el equipo se vuelve a bajar (y el aviso lo dice), para que no quede un borrado pendiente que se haría solo si más adelante dan permiso.
- **Archivos más grandes de lo que admite el servidor:** avisa con los nombres y no los vuelve a subir hasta que cambien.
- **Descargas cortadas a medias** (el servidor cierra la conexión, p. ej. al desactivar la cuenta): se tratan como un error de red y nunca se guarda un archivo incompleto.
- Los archivos `storageweb://` abiertos dejan de comprobarse si el servidor rechaza las credenciales o la IP (seguir preguntando solo sumaría intentos fallidos) y se avisa una vez. Subir varios archivos se para en el primer error que afectaría a todos (sin red, sin permiso…), con un solo aviso.

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

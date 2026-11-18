# 0019. En Windows, servicio propio sin dependencias y Caddy para el HTTPS

- **Estado:** Aceptada
- **Fecha:** 2026-11-18

## Contexto

En Linux, StorageWeb corre como servicio systemd con un usuario propio ([0009](0009-usuario-de-servicio.md)) detrás de nginx o Apache. En Windows (sobre todo en un Windows 10/11 Pro de una oficina pequeña) no había nada: había que dejar una consola abierta con `storageweb serve`, y Waitress no cifra ([0001](0001-python-flask-waitress.md)).

- **IIS** no sirve en las ediciones cliente: atiende como mucho 10 peticiones a la vez. Su proxy (ARR) está pensado para Windows Server, su módulo WebDAV intercepta la unidad de red y no admite peticiones de más de 4 GB.
- Un servicio de Windows necesita que el proceso que arrancó el Administrador de servicios hable con él. En un venv de Windows, `python.exe` es un **lanzador** que abre otro proceso, así que el servicio no puede ser `venv\Scripts\python.exe`. pywin32 tiene el mismo problema con su `pythonservice.exe` dentro de un venv.

## Decisión

- **HTTPS con Caddy** delante, igual que nginx o Apache en Linux. Caddy es un solo ejecutable, renueva el certificado él solo (también por DNS para una red interna) y no tiene los límites de IIS. Su plantilla (`packaging/caddy/Caddyfile`) se instala con las de nginx y Apache.
- **Comando `storageweb service install|remove|start|stop|status`**, sin dependencias:
    - registra el servicio con `sc.exe`: inicio automático retrasado, se reinicia si cae o acaba con error;
    - el servicio ejecuta el **intérprete base** con `-S -I` y `cli/service_boot.py`, que añade las `site-packages` del venv (con sus `.pth`) y pasa a `cli/service_host.py`, que habla con el Administrador de servicios con `ctypes` (`advapi32`);
    - para pararse, cierra todas las conexiones de Waitress desde su propio bucle (`trigger.pull_trigger`), también las keep-alive.
- **Cuenta virtual** `NT SERVICE\<nombre>`: sin contraseña ni privilegios. `icacls` le da lectura sobre Python, el venv y `config.json`, y escritura sobre los datos, las carpetas personales y las compartidas locales. Es el equivalente del usuario `storageweb` de Linux. `--account LocalSystem` queda como escape.

## Alternativas consideradas

- **HTTPS dentro de StorageWeb** (Cheroot en vez de Waitress con certificado): sin programas de terceros, pero el certificado (pedirlo, renovarlo y recargarlo) quedaba a nuestro cargo, y habría dos servidores web que mantener.
- **IIS con ARR:** por los límites de arriba.
- **pywin32:** una dependencia solo de Windows, con el problema del venv y la instalación de sus DLL (`pywin32_postinstall`).
- **WinSW o NSSM:** otro ejecutable que descargar y mantener.
- **Tarea programada** al iniciar el equipo: no es un servicio. Se para a las 72 horas por defecto y controla peor los reinicios y la parada.

## Consecuencias

- Windows queda como plataforma de producción para instalaciones pequeñas, con dos servicios (StorageWeb y Caddy) y sin IIS.
- La parte de `ctypes` solo se prueba de verdad en Windows y como administrador. Las órdenes (`sc.exe`, `icacls`, la línea del servicio) y la parada de Waitress tienen pruebas en cualquier sistema.
- Las carpetas que se añadan después fuera de las que ya tienen permiso necesitan un `icacls` a mano (la guía lo dice).
- Cambiar de versión de Python obliga a volver a crear el venv y el servicio, porque la orden del servicio apunta al intérprete base.

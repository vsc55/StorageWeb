# 0008. Paquetes con wheel + venv y dependencias incluidas

- **Estado:** Aceptada
- **Fecha:** 2026-11-12

## Contexto

Las dependencias (Flask, Werkzeug…) existen en las distribuciones, pero en versiones distintas y a veces antiguas. Depender de los paquetes del sistema obligaría a probar cada combinación. Además, algunos servidores no tienen salida a Internet en el momento de la instalación.

## Decisión

- **Instalación en venv:** los `.deb` y `.rpm` instalan StorageWeb en un venv propio (`/opt/storageweb/venv`) creado en el *postinstall* con el Python del sistema.
- **Wheels incluidos:** el paquete trae el wheel de la aplicación y los de sus dependencias para Python 3.9–3.14 y la arquitectura correspondiente (manylinux). Así se instala sin conexión. Si falta alguno, se recurre a PyPI.
- **Recreación del venv:** si cambia la versión de Python del sistema, el venv se recrea.
- **Gentoo:** se usan las dependencias del sistema (distutils-r1), como manda la convención de la distribución.
- **Docker:** imagen multi-etapa que construye los wheels y los instala en `python:slim`.

## Alternativas consideradas

- **Dependencias de la distribución en deb/rpm:** versiones dispares entre distribuciones y más difíciles de probar.
- **Binario congelado (PyInstaller):** muy grande, y dificulta los parches de seguridad de Python.
- **Solo PyPI en el postinstall:** falla sin conexión.

## Consecuencias

- Mismo comportamiento en todas las distribuciones y la instalación no necesita Internet.
- Paquetes de varios MB y específicos por arquitectura (amd64 y arm64).
- Las actualizaciones de seguridad de las dependencias llegan con una nueva release de StorageWeb, no con las actualizaciones del sistema. Hay que publicar releases cuando una dependencia tenga un CVE.

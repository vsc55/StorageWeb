# 0001. Python, Flask y Waitress

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Hace falta un servidor web de archivos que se instale en Ubuntu y también funcione en Windows y macOS. Debe ser fácil de mantener por un equipo pequeño y tener pocas dependencias.

## Decisión

- **Python ≥ 3.9 + Flask:** web con plantillas Jinja2.
- **Waitress:** servidor WSGI de producción. Es Python puro y funciona igual en los tres sistemas.
- **SQLite:** estado (usuarios, ajustes, auditoría). Los archivos van en el sistema de ficheros.
- **Frontend sin framework:** HTML del servidor, CSS y un JS pequeño para las subidas. Sin paso de compilación.

## Alternativas consideradas

- **FastAPI + Uvicorn:** asíncrono y con buena API JSON, pero la aplicación es sobre todo HTML del servidor. Además, Gunicorn no funciona en Windows.
- **Django:** demasiado para el tamaño del proyecto; el ORM y el panel de administración propios no aportan lo suficiente.
- **Nextcloud u otras soluciones existentes:** mucho más pesadas, con PHP y su propia base de datos, y sin encajar en los requisitos de despliegue y autenticación.
- **PostgreSQL:** otro servicio que operar, sin necesidad real con una sola instancia.

## Consecuencias

- Instalación sencilla: un venv y un fichero de configuración.
- Una instancia con hilos. SQLite limita a una escritura a la vez, suficiente para el uso previsto (ver [Arquitectura](../index.md#procesos-y-concurrencia)).
- Escalar horizontalmente requeriría otra base de datos y compartir el estado de los bloqueos de login.

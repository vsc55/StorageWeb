"""Ajustes desde la web (solo rol admin): un blueprint, un módulo por tema.

* ``forms``    — una página por sección con su formulario (se aplica al guardar), restablecer campos
* ``branding`` — subir y quitar el logo
* ``ips``      — IPs bloqueadas y lista blanca
* ``sessions`` — cerrar sesiones y revocar tokens de API (de cualquier usuario)
* ``backups``  — copias de seguridad, compactar la base de datos y limpiar la auditoría
* ``entra``    — Entra ID: probar la conexión, asistente y registro con código de dispositivo
* ``security_status`` — Estado de la seguridad: tablero, lista de comprobación y vulnerabilidades
* ``passwords`` — la lista de contraseñas comunes: descargarla, subir una o volver a la de serie
* ``system``   — Información: versión, proceso, máquina, base de datos, carpetas, componentes y su informe
* ``common``   — guardar un cambio parcial, leer el formulario, diagnóstico de red de la petición

Cada sección guarda solo sus campos: se combinan sobre los ajustes efectivos y ``RuntimeSettings.save``
guarda la diferencia con los valores predeterminados. Cada campo sabe de dónde sale su valor
(``origins``: web, config.json o entorno); los de la web se restablecen uno a uno y los de config.json
o del entorno están bloqueados.
"""
from __future__ import annotations

from flask import Blueprint

bp = Blueprint("settings", __name__, url_prefix="/admin/settings")

from . import backups, branding, entra, forms, ips, passwords, security_status, sessions, system  # noqa: E402,F401  (registran sus rutas)
from .common import save_partial  # noqa: E402,F401

"""Lógica de negocio: seguridad, almacenamiento, permisos y cuentas (sin dependencias de Flask).

Al importar el paquete se registran los tipos de ubicación de almacenamiento (``backends.discover``).
"""
from . import backends  # noqa: F401  (registra S3, SMB… en settings.location_types)

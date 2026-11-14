"""Error de configuración, con la ruta del campo afectado para mostrarlo junto a él en la web."""
from __future__ import annotations


class ConfigError(Exception):
    """Configuración no válida. ``field`` es la ruta del ajuste afectado (``storage.home_template``)."""

    def __init__(self, message: str = "", field: str | None = None):
        super().__init__(message)
        self.field = field

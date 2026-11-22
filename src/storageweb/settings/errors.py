"""Error de configuración, con la ruta del campo afectado para mostrarlo junto a él en la web."""
from __future__ import annotations


class UserError(Exception):
    """Algo que no se puede hacer, con un mensaje para la persona que lo intentó (``message``). La base de los
    errores de ``core`` (grupos, roles, enlaces, cuotas…), de los backends y de los métodos de inicio de sesión."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConfigError(Exception):
    """Configuración no válida. ``field`` es la ruta del ajuste afectado (``storage.home_template``)."""

    def __init__(self, message: str = "", field: str | None = None):
        super().__init__(message)
        self.field = field

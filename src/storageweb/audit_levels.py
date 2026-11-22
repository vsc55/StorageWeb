"""Niveles de la auditoría: cada evento de ``audit_log`` tiene uno (``level``), según su acción.

- ``debug``: consultas y preferencias (listar una carpeta, buscar, abrir en el visor, favoritos, tema, idioma).
- ``info``: lo que se hace normalmente (entrar, subir, descargar, crear, renombrar, cambiar ajustes…).
- ``warning``: intentos rechazados (contraseña o código erróneo, acceso denegado, CSRF no válido, una prueba que
  falla…).
- ``error``: fallos del sistema (una copia automática que no se hizo o no se pudo enviar fuera).
- ``critical``: incidentes de seguridad y cambios que no se deshacen (bloqueos por intentos, una IP bloqueada,
  restaurar una copia, borrar un usuario, descartar los ajustes, purgar la auditoría…).

Qué se guarda (``audit.min_level``, «debug» = todo) y qué se reenvía al SIEM (``audit.forward_min_level``) lo
ajusta el administrador; :func:`configure` lo aplica al proceso (web y CLI). Sin dependencias.
"""
from __future__ import annotations

LEVELS = ("debug", "info", "warning", "error", "critical")
RANK = {level: i for i, level in enumerate(LEVELS)}

DEBUG = frozenset({"favorite_added", "favorite_removed", "preference_changed", "folder_listed", "search",
                   "mfa_enrol_started", "upload_started"})
WARNING = frozenset({"login_failed", "link_password_failed", "mfa_failed", "login_denied", "password_change_failed", "user_rename_failed",
                     "entra_app_register_failed", "access_denied", "csrf_rejected", "mfa_disabled", "passkey_removed", "password_reset_by_admin",
                     "quota_exceeded"})
ERROR = frozenset({"backup_failed", "backup_offsite_failed"})
CRITICAL = frozenset({"login_blocked", "ip_banned", "backup_restored", "restore", "settings_reset",
                      "secrets_key_rotated", "mfa_reset_by_admin", "user_deleted", "audit_purged"})
# Pruebas: «ok» es info; cualquier otro resultado, aviso
TESTS = frozenset({"location_tested", "audit_forward_test", "entra_tested"})

_minimum = "debug"


def level_of(action: str, detail: str | None = None) -> str:
    """El nivel de un evento por su acción (y, en unas pocas, por su detalle)."""
    if action in CRITICAL:
        return "critical"
    if action in ERROR:
        return "error"
    if action in WARNING:
        return "warning"
    if action in DEBUG:
        return "debug"
    if action in TESTS:
        return "info" if (detail or "").split(";")[0].strip() == "ok" else "warning"
    if action == "download" and (detail or "").startswith("view"):
        return "debug"          # abrir en el visor: una consulta
    return "info"


def at_least(level: str, minimum: str) -> bool:
    return RANK.get(level, 1) >= RANK.get(minimum, 0)


def configure(minimum: str | None) -> None:
    """``audit.min_level``: lo que esté por debajo no se guarda (ni se reenvía)."""
    global _minimum  # noqa: PLW0603 (ajuste del proceso)
    _minimum = minimum if minimum in RANK else "debug"


def recorded(level: str) -> bool:
    return at_least(level, _minimum)


def levels_from(minimum: str) -> tuple[str, ...]:
    """Los niveles desde ``minimum`` hacia arriba (filtros de la página de auditoría)."""
    return tuple(level for level in LEVELS if at_least(level, minimum))

"""Tareas en segundo plano: el mantenimiento periódico (retención de la auditoría, limpiezas, copias)."""
from __future__ import annotations

import threading
import time

from flask import current_app

from .. import audit_levels, siem
from ..core import maintenance, quota
from ..db import connect

INTERVAL_SECONDS = 600


def apply_process_settings() -> None:
    """Lo que vive en el proceso y no en cada petición toma los ajustes efectivos (barato si no cambiaron): el
    reenvío de la auditoría al SIEM y cada cuánto se reconcilia el uso de las cuotas. Va antes de todo lo que pueda auditar (bloqueos de IP, inicios de sesión)."""
    from .context import settings
    try:
        siem.configure(settings()["audit"])
        audit_levels.configure(settings()["audit"]["min_level"])
        quota.configure(settings()["storage"]["quota_refresh_minutes"])
    except Exception:  # noqa: BLE001 (nunca puede tumbar una petición)
        current_app.logger.exception("Could not apply the audit forwarding settings")


def maintenance_tick() -> None:
    """Cada 10 minutos lanza las tareas de mantenimiento en un hilo (nunca en los tests)."""
    if current_app.testing:
        return
    state = current_app.extensions["storageweb.maintenance"]
    now = time.monotonic()
    with state["lock"]:
        if now < state["next"]:
            return
        state["next"] = now + INTERVAL_SECONDS
    runtime_settings = current_app.extensions["storageweb.runtime"]
    database = current_app.config["SW"]["database"]
    logger = current_app.logger

    def work():
        conn = connect(database)
        try:
            maintenance.run_due(conn, runtime_settings.current(conn))
        except Exception:  # noqa: BLE001 (un fallo de mantenimiento no debe afectar al servicio)
            logger.exception("Maintenance task failed")
        finally:
            conn.close()

    threading.Thread(target=work, name="storageweb-maintenance", daemon=True).start()

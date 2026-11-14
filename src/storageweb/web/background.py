"""Tareas en segundo plano: el mantenimiento periódico (retención de la auditoría, limpiezas, copias)."""
from __future__ import annotations

import threading
import time

from flask import current_app

from ..core import maintenance
from ..db import connect

INTERVAL_SECONDS = 600


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

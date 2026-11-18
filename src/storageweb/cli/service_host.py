"""El proceso del servicio de Windows (lo instala ``storageweb service install``, ``cli/service.py``).

Sin pywin32: la API de servicios de ``advapi32`` con ``ctypes``. El Administrador de servicios arranca el
intérprete base (no el del venv: en Windows, el ``python.exe`` de un venv es un lanzador que abre otro
proceso, y solo el proceso que arrancó el Administrador puede hablar con él) con ``service_boot.py``, que
añade las rutas del venv y llama a :func:`run`.

:class:`Runner` (Waitress que se para desde otro hilo) no depende de Windows y se prueba en cualquier
sistema; lo de ``ctypes`` solo se carga dentro de :func:`run`.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import tempfile
import threading
from pathlib import Path

log = logging.getLogger("storageweb.service")

# Constantes de winsvc.h
SERVICE_WIN32_OWN_PROCESS = 0x10
SERVICE_STOPPED, SERVICE_START_PENDING, SERVICE_STOP_PENDING, SERVICE_RUNNING = 1, 2, 3, 4
SERVICE_ACCEPT_STOP, SERVICE_ACCEPT_SHUTDOWN = 0x1, 0x4
SERVICE_CONTROL_STOP, SERVICE_CONTROL_INTERROGATE, SERVICE_CONTROL_SHUTDOWN = 1, 4, 5
NO_ERROR = 0
ERROR_CALL_NOT_IMPLEMENTED = 120
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063
ERROR_SERVICE_SPECIFIC_ERROR = 1066

LOG_NAME = "service.log"


class Runner:
    """La aplicación en Waitress, con una parada que se puede pedir desde cualquier hilo."""

    def __init__(self, config: str | None, port: int | None = None):
        self.config = config
        self.port = port                     # None: server.port (las pruebas usan 0, uno libre)
        self.server = None
        self._lock = threading.Lock()
        self._stopping = False

    def start(self) -> bool:
        """Crea la aplicación y el servidor (escuchando ya). False si antes se pidió parar."""
        from .. import create_app
        from .server import create_waitress

        app = create_app(self.config)
        server = create_waitress(app, port=self.port)
        with self._lock:
            if self._stopping:
                _close_all(server)
                return False
            self.server = server
        srv = app.config["SW"]["server"]
        log.info("StorageWeb service listening on http://%s:%s (config: %s)", srv["host"], server.effective_port,
                 app.config["SW"]["_config_path"])
        return True

    def run(self) -> None:
        """Atiende peticiones hasta que :meth:`stop` cierra todas las conexiones."""
        try:
            self.server.run()
        finally:
            self.server.task_dispatcher.shutdown()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            server = self.server
        if server is None:
            return
        trigger = getattr(server, "trigger", None)
        if trigger is not None:
            # Se cierra desde el bucle de Waitress (no es seguro tocar sus sockets desde otro hilo): sin
            # conexiones ni socket de escucha, el bucle termina y run() vuelve
            trigger.pull_trigger(lambda: _close_all(server))
        else:
            _close_all(server)


def _close_all(server) -> None:
    from waitress import wasyncore

    socket_map = getattr(server, "_map", None)
    wasyncore.close_all(socket_map if socket_map is not None else server.map, ignore_all=True)


def log_path(config: str | None) -> Path:
    """``<data_dir>/logs/service.log``; si la configuración no se puede leer, en la carpeta temporal."""
    try:
        from ..settings import load_config

        logs = Path(load_config(config)["data_dir"]) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        return logs / LOG_NAME
    except Exception:  # noqa: BLE001 — con la configuración rota también hay que poder decir por qué
        return Path(tempfile.gettempdir()) / f"storageweb-{LOG_NAME}"


def _setup_logging(config: str | None) -> Path:
    path = log_path(config)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)       # create_app llama a basicConfig, que no hace nada si ya hay un handler
    root.setLevel(logging.INFO)
    logging.getLogger("waitress").setLevel(logging.INFO)
    return path


def run(name: str, config: str | None) -> int:
    """Punto de entrada del proceso del servicio. Fuera del Administrador de servicios no hace nada."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class SERVICE_STATUS(ctypes.Structure):  # noqa: N801 — nombres de la API de Windows
        _fields_ = [("dwServiceType", wintypes.DWORD), ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD), ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD), ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    SERVICE_MAIN = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))  # noqa: N806
    HANDLER_EX = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,  # noqa: N806
                                    wintypes.LPVOID, wintypes.LPVOID)

    class SERVICE_TABLE_ENTRYW(ctypes.Structure):  # noqa: N801
        _fields_ = [("lpServiceName", wintypes.LPWSTR), ("lpServiceProc", SERVICE_MAIN)]

    advapi32.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(SERVICE_TABLE_ENTRYW)]
    advapi32.StartServiceCtrlDispatcherW.restype = wintypes.BOOL
    advapi32.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, HANDLER_EX, wintypes.LPVOID]
    advapi32.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    advapi32.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(SERVICE_STATUS)]
    advapi32.SetServiceStatus.restype = wintypes.BOOL

    path = _setup_logging(config)
    runner = Runner(config)
    state = {"handle": None, "checkpoint": 0}

    def report(current: int, *, wait_hint: int = 0, exit_code: int = NO_ERROR, specific: int = 0) -> None:
        pending = current in (SERVICE_START_PENDING, SERVICE_STOP_PENDING)
        state["checkpoint"] = state["checkpoint"] + 1 if pending else 0
        status = SERVICE_STATUS(
            SERVICE_WIN32_OWN_PROCESS, current,
            SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN if current == SERVICE_RUNNING else 0,
            exit_code, specific, state["checkpoint"], wait_hint)
        advapi32.SetServiceStatus(state["handle"], ctypes.byref(status))

    def handler(control, _event_type, _event_data, _context):
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            log.info("Stopping the StorageWeb service")
            report(SERVICE_STOP_PENDING, wait_hint=20000)
            runner.stop()
            return NO_ERROR
        if control == SERVICE_CONTROL_INTERROGATE:
            return NO_ERROR
        return ERROR_CALL_NOT_IMPLEMENTED

    def service_main(_argc, _argv):
        state["handle"] = advapi32.RegisterServiceCtrlHandlerExW(name, handler_ref, None)
        report(SERVICE_START_PENDING, wait_hint=60000)
        try:
            if runner.start():
                report(SERVICE_RUNNING)
                runner.run()
        except Exception:  # noqa: BLE001 — se registra y el servicio acaba con error (y se reinicia)
            log.exception("The StorageWeb service failed")
            report(SERVICE_STOPPED, exit_code=ERROR_SERVICE_SPECIFIC_ERROR, specific=1)
            return
        log.info("StorageWeb service stopped")
        report(SERVICE_STOPPED)

    # Referencias vivas mientras dure el proceso: si el recolector las libera, Windows llamaría a la nada
    handler_ref = HANDLER_EX(handler)
    main_ref = SERVICE_MAIN(service_main)
    table = (SERVICE_TABLE_ENTRYW * 2)(SERVICE_TABLE_ENTRYW(name, main_ref), SERVICE_TABLE_ENTRYW(None, SERVICE_MAIN()))
    if not advapi32.StartServiceCtrlDispatcherW(table):
        error = ctypes.get_last_error()
        if error == ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
            from ..i18n import _, from_environment, set_locale

            set_locale(from_environment())
            print(_("This program is started by the Windows service manager (storageweb service start). "
                    "To run StorageWeb in a console: storageweb serve."), file=sys.stderr)
            return 1
        log.error("StartServiceCtrlDispatcher failed: %s", ctypes.FormatError(error))
        return 1
    log.debug("Service log: %s", path)
    return 0

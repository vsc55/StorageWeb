"""Comando ``service``: StorageWeb como servicio de Windows (instalar, quitar, arrancar, parar, estado).

En Linux lo hacen los paquetes con systemd. En Windows, ``service install`` lo registra con ``sc.exe``:

- arranca solo con el equipo (inicio automático retrasado), sin sesión iniciada, y se reinicia si cae;
- con la **cuenta virtual** ``NT SERVICE\\<nombre>`` (sin contraseña ni permisos de administrador), a la que
  ``icacls`` da lectura sobre Python, el venv y config.json, y escritura sobre la carpeta de datos, la de las
  carpetas personales y las carpetas compartidas locales;
- ejecuta el **intérprete base** con ``service_boot.py`` (el ``python.exe`` de un venv es un lanzador que abre
  otro proceso, y el Administrador de servicios solo habla con el que arrancó). El proceso del servicio está
  en ``service_host.py``, sin pywin32.

Las órdenes (``service_steps``, ``grants``…) son funciones puras para probarlas en cualquier sistema.
"""
from __future__ import annotations

import re
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

from ..i18n import _, _l
from ..settings import ConfigError, default_config_path
from .common import command

SERVICE_NAME = "StorageWeb"
ACTIONS = ("install", "remove", "start", "stop", "status")
VIRTUAL = "virtual"
LOCAL_SYSTEM = "LocalSystem"
# Reinicios si el proceso cae o acaba con error: a los 5 s, a los 10 s y luego cada minuto; la cuenta se
# pone a cero tras un día sin fallos
FAILURE_ACTIONS = "restart/5000/restart/10000/restart/60000"
ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_SERVICE_EXISTS = 1073
STATES = ("STOPPED", "START_PENDING", "STOP_PENDING", "RUNNING", "CONTINUE_PENDING", "PAUSE_PENDING", "PAUSED")


def _service_args(p):
    p.add_argument("action", choices=ACTIONS,
                   help=_("install, remove, start, stop or status"))
    p.add_argument("--name", default=SERVICE_NAME, help=_("Name of the service (default StorageWeb)"))
    p.add_argument("--account", default=VIRTUAL, choices=(VIRTUAL, LOCAL_SYSTEM),
                   help=_("Account that runs it: «virtual» (default: NT SERVICE\\<name>, with access only to "
                          "the folders it needs) or LocalSystem (full access to the computer)"))


def account_name(name: str, account: str) -> str:
    return f"NT SERVICE\\{name}" if account == VIRTUAL else account


def interpreter() -> Path:
    """El ``python.exe`` real (el base, no el lanzador del venv)."""
    return Path(getattr(sys, "_base_executable", "") or sys.executable)


def site_paths() -> list[str]:
    """Donde está instalado StorageWeb (las ``site-packages`` del venv y, si es editable, su ``src``)."""
    paths = []
    for key in ("purelib", "platlib"):
        path = sysconfig.get_paths()[key]
        if path not in paths:
            paths.append(path)
    package_root = str(Path(__file__).resolve().parents[2])   # la carpeta que contiene «storageweb»
    if not any(Path(package_root).is_relative_to(p) for p in paths):
        paths.append(package_root)
    return paths


def command_line(name: str, config: Path, python: Path, paths: list[str]) -> str:
    """La orden que ejecuta el Administrador de servicios (``binPath``). ``-S -I``: sin las site-packages
    del Python base ni variables PYTHON*, solo las del venv (``--path``)."""
    boot = Path(__file__).with_name("service_boot.py")
    parts = [str(python), "-S", "-I", str(boot), "--name", name, "--config", str(config)]
    for path in paths:
        parts += ["--path", path]
    return subprocess.list2cmdline(parts)


def home_base(template: str) -> Path | None:
    """La carpeta que contiene las personales: lo que hay antes de ``{username}``."""
    parts = Path(template).parts
    for i, part in enumerate(parts):
        if "{username}" in part:
            return Path(*parts[:i]) if i else None
    return None


def grants(cfg: dict, config: Path, python: Path, paths: list[str]) -> list[tuple[Path, str]]:
    """Permisos de la cuenta virtual: ``RX`` (carpeta, heredado), ``R`` (fichero) o ``M`` (modificar)."""
    out: list[tuple[Path, str]] = [(python.parent, "RX"), *((Path(p), "RX") for p in paths), (config, "R"),
                                   (Path(cfg["data_dir"]), "M")]
    storage = cfg["storage"]
    if not storage["home_location"]:
        base = home_base(storage["home_template"])
        if base is not None:
            out.append((base, "M"))
    for share in storage["shares"]:
        if not share.get("location") and share.get("path"):
            out.append((Path(share["path"]), "M"))
    seen, unique = set(), []
    for path, perm in out:
        if (str(path).lower(), perm) not in seen:
            seen.add((str(path).lower(), perm))
            unique.append((path, perm))
    return unique


def icacls(account: str, path: Path, perm: str) -> list[str]:
    ace = f"{account}:{perm}" if perm == "R" else f"{account}:(OI)(CI){perm}"
    return ["icacls", str(path), "/grant", ace]


def service_steps(name: str, account: str, binpath: str) -> list[list[str]]:
    """Las órdenes de ``sc.exe`` para registrar el servicio."""
    steps = [["sc.exe", "create", name, "binPath=", binpath, "start=", "delayed-auto", "DisplayName=", name]]
    if account != LOCAL_SYSTEM:
        steps.append(["sc.exe", "config", name, "obj=", account_name(name, account)])
    steps += [["sc.exe", "description", name, "StorageWeb: file server (https://github.com/vsc55/StorageWeb)"],
              ["sc.exe", "failure", name, "reset=", "86400", "actions=", FAILURE_ACTIONS],
              ["sc.exe", "failureflag", name, "1"]]
    return steps


def parse_state(output: str) -> str | None:
    """El estado de ``sc query`` (``RUNNING``…). Los nombres de los estados no se traducen."""
    found = re.search(r":\s*\d+\s+(" + "|".join(STATES) + r")\b", output)
    return found.group(1) if found else None


# --------------------------------------------------------------------------- ejecución (solo Windows)

def _run(argv: list[str]) -> subprocess.CompletedProcess:
    # Las herramientas de consola de Windows escriben en la página de códigos OEM
    return subprocess.run(argv, capture_output=True, encoding="oem", errors="replace", check=False)


def _is_admin() -> bool:
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _query(name: str) -> str | None:
    """Estado del servicio, o None si no existe."""
    result = _run(["sc.exe", "query", name])
    if result.returncode == ERROR_SERVICE_DOES_NOT_EXIST:
        return None
    return parse_state(result.stdout) or "UNKNOWN"


def _wait(name: str, wanted: str, timeout: float = 60) -> str | None:
    end = time.monotonic() + timeout
    state = _query(name)
    while state not in (wanted, "STOPPED", None) and time.monotonic() < end:
        time.sleep(1)
        state = _query(name)
    return state


def _effective_config(config: Path) -> dict:
    """Configuración efectiva (también las carpetas compartidas creadas desde la web)."""
    from .. import create_app
    from ..web.context import settings

    app = create_app(str(config))
    with app.app_context():
        return settings()


def _log_hint(config: Path) -> str:
    from .service_host import log_path

    return _("Log: %(path)s", path=log_path(str(config)))


def _install(args, name: str, config: Path) -> int:
    python = interpreter()
    if "WindowsApps" in python.parts:
        print(_("The Python from the Microsoft Store cannot run services: install it from python.org "
                "(or with the Python install manager) and create the venv again."), file=sys.stderr)
        return 2
    try:
        cfg = _effective_config(config)
    except ConfigError as exc:
        print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
        return 2
    if _query(name) is not None:
        print(_("The service %(name)s already exists. Remove it first: storageweb service remove", name=name),
              file=sys.stderr)
        return 1
    paths = site_paths()
    binpath = command_line(name, config, python, paths)
    for step in service_steps(name, args.account, binpath):
        result = _run(step)
        if result.returncode != 0:
            print(_("«%(command)s» failed: %(output)s", command=" ".join(step[:3]),
                    output=(result.stdout or result.stderr).strip()), file=sys.stderr)
            if step[1] != "create":
                _run(["sc.exe", "delete", name])
            return 1
    print(_("Service %(name)s installed: it starts with the computer and restarts if it stops.", name=name))
    if args.account != LOCAL_SYSTEM:
        account = account_name(name, args.account)
        # Las carpetas de datos y la de las personales se crean; una compartida que aún no existe, no
        create = {Path(cfg["data_dir"]), home_base(cfg["storage"]["home_template"])}
        for path, perm in grants(cfg, config, python, paths):
            if path in create:
                path.mkdir(parents=True, exist_ok=True)
            elif not path.exists():
                continue
            result = _run(icacls(account, path, perm))
            if result.returncode != 0:
                print(_("Could not give %(account)s access to %(path)s: %(output)s", account=account, path=path,
                        output=(result.stdout or result.stderr).strip()), file=sys.stderr)
            else:
                print(_("  Read access: %(path)s", path=path) if perm in ("R", "RX")
                      else _("  Write access: %(path)s", path=path))
        print(_("Folders added later outside these (a shared folder on another disk) need the same access: "
                "icacls <folder> /grant \"%(account)s:(OI)(CI)M\"", account=account))
    srv = cfg["server"]
    if srv["host"] not in ("127.0.0.1", "localhost", "::1") and srv["behind_proxy"]:
        print(_("Warning: server.host is %(host)s. Behind Caddy, listen only on 127.0.0.1 so nobody can skip the "
                "proxy.", host=srv["host"]), file=sys.stderr)
    print(_("Start it with: storageweb service start"))
    return 0


def _remove(name: str) -> int:
    state = _query(name)
    if state is None:
        print(_("The service %(name)s is not installed.", name=name), file=sys.stderr)
        return 1
    if state != "STOPPED":
        _run(["sc.exe", "stop", name])
        _wait(name, "STOPPED", timeout=30)
    result = _run(["sc.exe", "delete", name])
    if result.returncode != 0:
        print((result.stdout or result.stderr).strip(), file=sys.stderr)
        return 1
    print(_("Service %(name)s removed. The access given to its account stays on the folders.", name=name))
    return 0


def _start(name: str, config: Path) -> int:
    state = _query(name)
    if state is None:
        print(_("The service %(name)s is not installed: storageweb service install", name=name), file=sys.stderr)
        return 1
    if state != "RUNNING":
        result = _run(["sc.exe", "start", name])
        if result.returncode != 0:
            print((result.stdout or result.stderr).strip(), file=sys.stderr)
        state = _wait(name, "RUNNING")
    if state == "RUNNING":
        print(_("Service %(name)s running.", name=name), _log_hint(config))
        return 0
    print(_("The service %(name)s did not start.", name=name), _log_hint(config), file=sys.stderr)
    return 1


def _stop(name: str) -> int:
    state = _query(name)
    if state is None:
        print(_("The service %(name)s is not installed.", name=name), file=sys.stderr)
        return 1
    if state != "STOPPED":
        _run(["sc.exe", "stop", name])
        state = _wait(name, "STOPPED", timeout=30)
    print(_("Service %(name)s stopped.", name=name) if state == "STOPPED"
          else _("The service %(name)s is still stopping.", name=name))
    return 0 if state == "STOPPED" else 1


def _status(name: str, config: Path) -> int:
    state = _query(name)
    if state is None:
        print(_("The service %(name)s is not installed.", name=name))
        return 3
    print(_("Service %(name)s: %(state)s", name=name, state=state), _log_hint(config))
    return 0 if state == "RUNNING" else 3


@command("service", _l("Windows service: install, remove, start, stop or status"), _service_args,
         needs_db=False, order=11)
def cmd_service(args) -> int:
    if sys.platform != "win32":
        print(_("Only on Windows. On Linux the packages install the systemd service (storageweb.service)."),
              file=sys.stderr)
        return 2
    name = args.name
    config = Path(args.config or default_config_path()).resolve()
    if args.action != "status" and not _is_admin():
        print(_("Run it from a terminal opened as administrator."), file=sys.stderr)
        return 2
    if args.action == "install":
        if not config.is_file():
            print(_("Configuration file not found: %(path)s (use --config)", path=config), file=sys.stderr)
            return 2
        return _install(args, name, config)
    if args.action == "remove":
        return _remove(name)
    if args.action == "start":
        return _start(name, config)
    if args.action == "stop":
        return _stop(name)
    return _status(name, config)

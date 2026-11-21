"""Qué es esta instalación, sacado del proceso en el que corre: *Sistema → Información* y su informe.

Contesta lo que se pregunta primero cuando algo falla: qué versión es, sobre qué corre, cómo se ejecuta, qué le falta
y dónde escribe. Basado en el diagnóstico de ServiceSentry (mismo autor).

* **Sin Flask, sin red.** Todo sale del proceso, del sistema de ficheros y de la base de datos que se le pasa; lo que
  ve la petición (proxy, HTTPS) ya lo cuenta *Red y HTTPS* (``core/network.diagnose``).
* **Nada lanza.** Una página de diagnóstico que falla es la única cuyo fallo no se puede diagnosticar: cada dato que
  no se puede averiguar dice ``""`` (la página enseña «desconocido»), nunca un 500.
* **Ningún secreto.** Versiones, rutas, cuentas y banderas. Las rutas ya las ve quien puede ver esta página.
* **Nada se escribe.** Si una carpeta se puede escribir se le pregunta al sistema (``os.access``), sin crear nada.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

from .. import __version__
from ..db.connection import available_migrations
from ..settings import location_types

# Cuándo arrancó este proceso, más o menos: el módulo se importa una vez, al arrancar (storageweb importa core)
STARTED = time.time()
DISTRIBUTION = "storageweb"
# El tipo de cada componente según su ecosistema (el de OSV.dev, PyPI y npm): la columna «Tipo» de *Información*.
# Un tipo nuevo (p. ej. un binario) es una línea aquí y su ecosistema en core/advisories
KINDS = {"PyPI": "Python", "npm": "JavaScript"}
# Extras de pyproject que no son del servidor (herramientas de desarrollo y documentación)
_TOOL_EXTRAS = frozenset({"dev", "docs"})


def _safe(fn, default=""):
    """``fn()``, o ``default`` si lanza lo que sea o no devuelve nada. Amplio a propósito: ``platform`` y ``os``
    fallan distinto en cada sistema (``OSError``, ``AttributeError`` si solo existe en Linux…) y un dato desconocido
    nunca puede costar los demás."""
    try:
        value = fn()
    except Exception:  # noqa: BLE001
        return default
    return default if value in (None, "") else value


# --------------------------------------------------------------------------- el proceso y la máquina

def container() -> str:
    """``docker``, ``podman``, ``container`` (otro) o ``""``. Cambia lo que significa todo lo demás: una carpeta
    que «existe» está dentro de una imagen que puede recrearse mañana."""
    if os.path.exists("/.dockerenv"):
        return "docker"
    if os.path.exists("/run/.containerenv"):
        return "podman"
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as fh:
            blob = fh.read()
    except OSError:
        return ""
    return "container" if any(k in blob for k in ("docker", "kubepods", "containerd", "lxc")) else ""


def run_mode(debug: bool = False) -> str:
    """Cómo se ejecuta: ``windows_service`` (``storageweb service``), ``container``, ``systemd``, ``dev``
    (``serve --dev``) o ``process`` (a mano o con otro supervisor)."""
    if Path(sys.argv[0] if sys.argv else "").name == "service_boot.py":
        return "windows_service"
    if container():
        return "container"
    if os.environ.get("INVOCATION_ID"):            # lo pone systemd a cada servicio que arranca
        return "systemd"
    return "dev" if debug else "process"


def _distribution_name() -> str:
    """El nombre que se da la distribución (``Debian GNU/Linux 12``), o el del sistema y su versión."""
    reader = getattr(platform, "freedesktop_os_release", None)       # Linux
    if reader is not None:
        data = _safe(reader, default={})
        if isinstance(data, dict) and data.get("PRETTY_NAME"):
            return data["PRETTY_NAME"]
    if platform.system() == "Windows":
        return " ".join(x for x in (_safe(platform.system), _safe(platform.release), _safe(platform.version)) if x)
    if platform.system() == "Darwin":
        return f"macOS {_safe(lambda: platform.mac_ver()[0])}".strip()
    return " ".join(x for x in (_safe(platform.system), _safe(platform.release)) if x)


def memory_total() -> int:
    """Memoria física del equipo en bytes, o 0 si no se sabe (sin dependencias)."""
    if hasattr(os, "sysconf"):
        total = _safe(lambda: os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"), default=0)
        if total:
            return int(total)
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        def _read():
            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            return status.ullTotalPhys if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0
        return int(_safe(_read, default=0))
    return 0


def _short_zone() -> str:
    """El nombre corto de la zona horaria (CET, UTC…), o ``""``: Windows da uno largo y traducido por el sistema
    («Hora estándar romance»), que saldría en ese idioma sea cual sea el de la página. El desfase va aparte."""
    name = str(_safe(lambda: time.strftime("%Z")))
    return name if name and len(name) <= 6 and name.replace("+", "").replace("-", "").isalnum() else ""


def system(debug: bool = False, threads: int = 0) -> dict:
    """El proceso y la máquina debajo."""
    now = time.time()
    load = _safe(os.getloadavg, default=None) if hasattr(os, "getloadavg") else None
    return {
        "version": __version__,
        "run_mode": run_mode(debug),
        "container": container(),
        "pid": os.getpid(),
        "started": datetime.fromtimestamp(STARTED, timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": int(now - STARTED),
        "threads": int(threads or 0),
        "python": _safe(platform.python_version),
        "python_impl": _safe(platform.python_implementation),
        "python_exe": sys.executable or "",
        "hostname": _safe(platform.node),
        "os": _distribution_name(),
        "kernel": " ".join(x for x in (_safe(platform.system), _safe(platform.release)) if x),
        "arch": _safe(platform.machine),
        "cpus": os.cpu_count() or 0,
        "memory": memory_total(),
        "load": [round(x, 2) for x in load] if load else [],
        # El desfase y no solo el nombre: es contra lo que se lee una hora que no cuadra (y los códigos de la app
        # de verificación dependen del reloj)
        "timezone": _short_zone(),
        "utc_offset": _safe(lambda: time.strftime("%z")),
        "now": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------- base de datos

def database(conn: sqlite3.Connection, path: str) -> dict:
    """El motor, la versión del esquema frente a las migraciones que trae esta versión, el modo y el tamaño."""
    files = [Path(path + suffix) for suffix in ("", "-wal")]
    latest = _safe(lambda: available_migrations()[-1][0], default=0)
    schema = _safe(lambda: conn.execute("PRAGMA user_version").fetchone()[0], default=0)
    return {"engine": f"SQLite {sqlite3.sqlite_version}", "path": path,
            "size": sum(_safe(lambda f=f: f.stat().st_size, default=0) for f in files),
            "wal_size": _safe(lambda: files[1].stat().st_size, default=0),
            "schema": int(schema), "latest": int(latest),
            "journal": str(_safe(lambda: conn.execute("PRAGMA journal_mode").fetchone()[0])).upper()}


# --------------------------------------------------------------------------- carpetas

def folders(entries: list[dict]) -> list[dict]:
    """Por cada carpeta ``{key, path, on_demand}``: si existe, si se puede escribir y el espacio libre.

    Una carpeta que se crea la primera vez que hace falta (``on_demand``) y aún no existe no es un fallo. El espacio
    se da solo en la PRIMERA carpeta de cada sistema de ficheros: cinco veces el mismo disco no son cinco respuestas,
    y lo que es noticia es una carpeta en un disco propio."""
    out, seen = [], set()
    for e in entries:
        path = str(e.get("path") or "")
        row = {"key": e["key"], "path": path, "on_demand": bool(e.get("on_demand")), "exists": False,
               "writable": False, "free": 0, "total": 0}
        if path:
            row["exists"] = os.path.isdir(path)
            row["writable"] = bool(row["exists"] and os.access(path, os.W_OK))
            if row["exists"]:
                dev = _safe(lambda p=path: os.stat(p).st_dev, default=None)
                if dev is None or dev not in seen:
                    seen.add(dev)
                    usage = _safe(lambda p=path: shutil.disk_usage(p), default=None)
                    if usage is not None:
                        row["free"], row["total"] = int(usage.free), int(usage.total)
        out.append(row)
    return out


def home_base(template: str) -> str:
    """La carpeta donde están las personales (``storage.home_template`` hasta ``{username}``)."""
    head = str(template or "").split("{username}")[0].rstrip("/\\")
    return head or ""


# --------------------------------------------------------------------------- componentes

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;]*?)\s*(?:;\s*(.*))?$")


def _marker(text: str) -> tuple[str, bool]:
    """``(extra, aplica)`` de un marcador de pyproject: el extra que lo pide (``""`` si es necesaria) y si aplica en
    este sistema. Solo lo que usa StorageWeb: ``extra == "x"`` y ``sys_platform ==/!= "x"``."""
    extra = re.search(r"""extra\s*==\s*["']([^"']+)["']""", text or "")
    platform_check = re.search(r"""sys_platform\s*(==|!=)\s*["']([^"']+)["']""", text or "")
    applies = True
    if platform_check:
        same = sys.platform == platform_check.group(2)
        applies = same if platform_check.group(1) == "==" else not same
    return (extra.group(1) if extra else ""), applies


def _installed(name: str) -> str:
    return str(_safe(lambda: metadata.version(name)))


def components() -> dict:
    """Las bibliotecas que declara StorageWeb (pyproject) con lo instalado al lado: ``required`` (necesarias en este
    sistema: ``ok`` o ``missing``) y ``optional`` (los extras, cada uno con lo que activa; los tipos de ubicación
    los nombra su propio esquema). Sin metadatos (código sin instalar), ``found`` es False."""
    requires = _safe(lambda: metadata.requires(DISTRIBUTION), default=None)
    # Los metadatos instalados son de otra versión que el código (``pip install -e .`` de hace tiempo, o un paquete
    # a medias): la lista de abajo es la de entonces, y lo que se añadió después no sale como «falta»
    dist_version = _installed(DISTRIBUTION)
    stale = bool(dist_version) and dist_version != __version__
    if not requires:
        return {"found": False, "required": [], "optional": [], "missing": 0, "dist_version": dist_version,
                "stale": stale}
    required, optional = [], []
    for line in requires:
        match = _REQ_RE.match(line)
        if not match:
            continue
        name, spec, marker = match.group(1), match.group(2).strip(), match.group(3) or ""
        extra, applies = _marker(marker)
        if not applies or extra in _TOOL_EXTRAS:
            continue
        have = _installed(name)
        row = {"name": name, "spec": spec, "installed": have, "status": "ok" if have else "missing",
               "ecosystem": "PyPI", "kind": KINDS["PyPI"]}
        if extra:
            schema = location_types.get(extra)
            row.update(extra=extra, feature=str(schema.label) if schema else extra)
            optional.append(row)
        else:
            required.append(row)
    required.sort(key=lambda r: (r["status"] == "ok", r["name"].lower()))
    optional.sort(key=lambda r: (r["extra"], r["name"].lower()))
    return {"found": True, "required": required, "optional": optional,
            "missing": sum(1 for r in required if r["status"] == "missing"), "dist_version": dist_version,
            "stale": stale}


def vendored(vendor_dir: Path) -> list[dict]:
    """Las bibliotecas de JavaScript copiadas en ``static/vendor`` (``vendor.json``, lo escribe ``tools/vendor.py``):
    nombre, paquete, versión, el ajuste que las usa y ``status``: ``ok``, ``modified`` (algún fichero no es el
    copiado: alguien lo cambió a mano) o ``missing`` (falta alguno). Sin el manifiesto, ``[]``."""
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415
    data = _safe(lambda: json.loads((vendor_dir / "vendor.json").read_text(encoding="utf-8")), default={})
    out = []
    for name, lib in sorted((data or {}).items()):
        status = "ok"
        for rel, digest in (lib.get("files") or {}).items():
            path = vendor_dir / rel
            if not path.is_file():
                status = "missing"
                break
            if _safe(lambda p=path: hashlib.sha256(p.read_bytes()).hexdigest()) != digest:
                status = "modified"
        package = str(lib.get("package") or name)
        out.append({"name": name, "package": package, "advisories": str(lib.get("advisories") or package),
                    "ecosystem": "npm", "kind": KINDS["npm"],
                    "version": str(lib.get("version") or ""), "setting": str(lib.get("setting") or ""),
                    "status": status})
    return out


_CANON_RE = re.compile(r"[-_.]+")


def canonical(name: str) -> str:
    """Un nombre de paquete como los compara PEP 503: minúsculas y cada tramo de ``-_.`` un guion."""
    return _CANON_RE.sub("-", str(name or "").strip()).lower()


def installed_packages() -> list[dict]:
    """Todo lo instalado en el entorno de Python (``{name, version}``), una vez cada uno: lo que se ejecuta en este
    servidor, también lo que nadie pidió a mano (las dependencias de las dependencias), que también puede tener
    avisos. El primero de cada nombre gana: es el que se importa."""
    out, seen = [], set()
    for dist in _safe(lambda: list(metadata.distributions()), default=[]):
        try:
            name, version = str((dist.metadata or {}).get("Name") or ""), str(dist.version or "")
        except Exception:  # noqa: BLE001 (un .dist-info a medias es una fila menos, nunca una página que falla)
            continue
        key = canonical(name)
        if key and version and key not in seen:
            seen.add(key)
            out.append({"name": name, "version": version})
    return sorted(out, key=lambda r: canonical(r["name"]))


def importable(module: str) -> bool:
    """Si un módulo se puede importar, sin importarlo (``find_spec``: importar para saberlo cuesta la importación)."""
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# --------------------------------------------------------------------------- el informe

def as_text(data: dict) -> str:
    """El informe en texto, para pegarlo en una incidencia: una sección por bloque, ``clave: valor``."""
    lines = [f"StorageWeb {data['system']['version']} — {data['generated']}", ""]
    for section, value in data.items():
        if section == "generated":
            continue
        lines.append(f"[{section}]")
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, list) and item and isinstance(item[0], dict):
                    lines.append(f"{key}:")
                    lines += [f"  - {_row(r)}" for r in item]
                else:
                    lines.append(f"{key}: {item}")
        elif isinstance(value, list):
            lines += [f"- {_row(r)}" for r in value]
        lines.append("")
    return "\n".join(lines)


def _row(row) -> str:
    return ", ".join(f"{k}={v}" for k, v in row.items()) if isinstance(row, dict) else str(row)

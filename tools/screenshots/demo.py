"""Instalación de demostración con datos inventados y capturas de pantalla para la documentación.

    python tools/screenshots/demo.py              # crea la demo, saca las capturas y las deja en docs/img/
    python tools/screenshots/demo.py --serve      # solo la deja en marcha para verla en el navegador
    python tools/screenshots/demo.py --only uso/  # solo las capturas cuyo fichero empieza así

Todo es inventado: personas, empresa, direcciones (rangos de documentación 192.0.2.0/24, 198.51.100.0/24 y
203.0.113.0/24) y el tenant de Entra ID. La demo vive en una carpeta temporal y no toca la instalación de
desarrollo. El proceso no puede conectarse fuera del propio equipo: ni siquiera llega a intentar hablar con
Microsoft con el tenant inventado.

Las capturas las hace ``capture.mjs`` (Node 18+, sin dependencias) manejando Microsoft Edge o Chrome sin
ventana por su protocolo de depuración. El navegador se busca en las rutas habituales o en ``STORAGEWEB_BROWSER``,
y Node en el PATH o en ``STORAGEWEB_NODE``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

PASSWORD = "demo-1234"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
TENANT = "8f2a6c1e-4b7d-4e19-9a3c-5d0e7f1b2c48"   # inventados
CLIENT = "3c9e1f7a-2d4b-4a8e-b6f0-91c2d5e8a7b3"


def _block_outbound() -> None:
    """La demo no sale del equipo: cualquier conexión que no sea local falla al momento."""
    real = socket.create_connection

    def local_only(address, *args, **kwargs):
        host = str(address[0])
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise OSError(f"Conexión bloqueada en la demo: {host}")
        return real(address, *args, **kwargs)

    socket.create_connection = local_only


SERVER_ROOT = "/srv/storageweb"   # cómo se ven las carpetas en las pantallas (las de un servidor Linux)


def _fake_disk(base: Path) -> None:
    """Lo que se ve del disco es inventado: las carpetas aparecen bajo /srv/storageweb (de verdad están en la
    carpeta temporal de la demo) y el espacio libre es el de un disco de 2 TB, no el de este equipo."""
    from storageweb.core import backends, locations
    from storageweb.core.backends.local import LocalBackend

    def real(path) -> str:
        text = str(path).replace("\\", "/")
        if len(text) > 2 and text[1] == ":":   # en Windows la configuración la vuelve absoluta: «D:/srv/…»
            text = text[2:]
        return str(base / text[len(SERVER_ROOT):].lstrip("/")) if text.startswith(SERVER_ROOT) else str(path)

    # En Windows «/srv/…» no es absoluta (le falta la unidad) y la configuración la uniría a su carpeta
    from pathlib import PurePosixPath

    from storageweb.settings import loader
    resolve = loader._resolve  # noqa: SLF001
    loader._resolve = lambda base_dir, value: (PurePosixPath(value) if str(value).startswith(SERVER_ROOT)  # noqa: SLF001
                                               else resolve(base_dir, value))

    backend_for, local_exists = backends.backend_for, locations.local_exists
    backends.backend_for = lambda location, path, staging: backend_for(location, real(path), staging)
    locations.local_exists = lambda location, path: local_exists(location, real(path))
    LocalBackend.space = lambda self, dir_rel="": {"total": 2 * 1024 ** 4, "free": int(1.22 * 1024 ** 4)}


def _ago(**delta) -> str:
    return (NOW - timedelta(**delta)).isoformat(timespec="seconds")


def _file(path: Path, size: int, days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.truncate(size)
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


def _folder(path: Path, days: float) -> None:
    path.mkdir(parents=True, exist_ok=True)
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))


KB, MB = 1024, 1024 * 1024

# Carpetas y archivos: (ruta relativa, tamaño en bytes o None para carpeta, hace cuántos días)
HOME_ANA = [
    ("Documentos", None, 2), ("Documentos/Contratos", None, 9), ("Documentos/Informes", None, 3),
    ("Documentos/Contratos/Contrato mantenimiento 2026.pdf", 1_240 * KB, 9),
    ("Documentos/Contratos/Anexo condiciones.pdf", 380 * KB, 9),
    ("Documentos/Informes/Informe ventas octubre.pdf", 2_100 * KB, 3),
    ("Documentos/Informes/Informe ventas septiembre.pdf", 1_950 * KB, 33),
    ("Fotos", None, 12), ("Fotos/Evento aniversario", None, 12),
    ("Fotos/Evento aniversario/IMG_2041.jpg", 4_300 * KB, 12), ("Fotos/Evento aniversario/IMG_2042.jpg", 3_900 * KB, 12),
    ("Presentaciones", None, 5),
    ("Presentaciones/Presentación clientes.pptx", 18 * MB, 5),
    ("Informe trimestral T3.pdf", 2_450 * KB, 1),
    ("Presupuesto 2026.xlsx", 86 * KB, 0.2),
    ("Notas reunión dirección.docx", 45 * KB, 0.8),
    ("Logo empresa.svg", 12 * KB, 40),
    ("Fotos evento.zip", 96 * MB, 12),
    ("Plan de proyecto.md", 6 * KB, 2),
]
SHARES = {
    "proyectos": [
        ("Web corporativa", None, 1), ("Web corporativa/Maquetas", None, 1),
        ("Web corporativa/Maquetas/Inicio v3.png", 1_800 * KB, 1),
        ("Web corporativa/Briefing web.pdf", 640 * KB, 20),
        ("Campaña primavera", None, 4), ("Campaña primavera/Carteles.psd", 210 * MB, 4),
        ("Catálogo 2026", None, 15), ("Catálogo 2026/Catálogo 2026.indd", 48 * MB, 15),
        ("Calendario de entregas.xlsx", 64 * KB, 0.5),
        ("Briefing cliente Norte.pdf", 820 * KB, 6),
    ],
    "contabilidad": [
        ("Facturas 2026", None, 2), ("Facturas 2026/F-2026-0412.pdf", 120 * KB, 2),
        ("Facturas 2026/F-2026-0413.pdf", 118 * KB, 1),
        ("Cierre trimestral T3.xlsx", 340 * KB, 10), ("Presupuesto 2026 (aprobado).xlsx", 92 * KB, 25),
    ],
    "plantillas": [
        ("Carta corporativa.docx", 54 * KB, 60), ("Presentación corporativa.potx", 2_300 * KB, 60),
        ("Hoja de gastos.xlsx", 38 * KB, 90), ("Manual de marca.pdf", 6_400 * KB, 120),
    ],
    "marketing": [
        ("Redes sociales", None, 3), ("Redes sociales/Publicaciones noviembre.xlsx", 72 * KB, 3),
        ("Fotos producto", None, 8), ("Fotos producto/Producto A.jpg", 3_100 * KB, 8),
        ("Plan de marketing 2026.pdf", 1_600 * KB, 14),
    ],
}

# (usuario, nombre, email, origen, rol, grupos de Entra o locales, opciones)
USERS = [
    ("ana.garcia", "Ana García", "ana.garcia@ejemplo.com", "local", "admin", {"quota_mb": 2048}),
    ("luis.martin", "Luis Martín", "luis.martin@ejemplo.com", "local", "user", {}),
    ("marta.lopez@ejemplo.com", "Marta López", "marta.lopez@ejemplo.com", "entra", "user",
     {"external_id": "a41f7c02-9d3e-4b8a-8c51-2e6f0b9d7a14"}),
    ("javier.moreno@ejemplo.com", "Javier Moreno", "javier.moreno@ejemplo.com", "entra", "admin",
     {"external_id": "c7d2e9a1-5b4f-4c3e-9f08-7a1b6d2e4c95"}),
    ("pedro.sanz", "Pedro Sanz", None, "pam", "user", {}),
    ("elena.navarro", "Elena Navarro", "elena.navarro@ejemplo.com", "local", "user", {"quota_mb": 1024}),
    ("carlos.diaz", "Carlos Díaz", "carlos.diaz@ejemplo.com", "local", "user", {}),
    ("sofia.ruiz", "Sofía Ruiz", "sofia.ruiz@ejemplo.com", "local", "user", {"enabled": False}),
]
GROUPS = [
    # (identificador, nombre, descripción, origen, id externo, miembros)
    ("diseno", "Diseño", "Equipo de diseño gráfico y web", "local", None, ["luis.martin", "elena.navarro"]),
    ("comerciales", "Comerciales", "Equipo comercial", "local", None, ["carlos.diaz", "elena.navarro", "sofia.ruiz"]),
    ("contabilidad", "Contabilidad", "Administración y contabilidad", "entra", "5e8b1d3c-7a2f-4c6e-b9d0-3f1a8e2c6b47",
     ["marta.lopez@ejemplo.com"]),
    ("direccion", "Dirección", "Comité de dirección", "entra", "9b4c2e7f-1d8a-4f3b-a6e5-0c7d9f2b1e83",
     ["javier.moreno@ejemplo.com"]),
]
AUDIT = [
    # (hace cuántos minutos, usuario, acción, objetivo, ip, detalle)
    (4, "ana.garcia", "upload", "home:Presupuesto 2026.xlsx", "192.0.2.15", None),
    (11, "marta.lopez@ejemplo.com", "login", None, "198.51.100.23", "entra"),
    (12, "marta.lopez@ejemplo.com", "download", "contabilidad:Cierre trimestral T3.xlsx", "198.51.100.23", None),
    (35, "luis.martin", "upload", "proyectos:Web corporativa/Maquetas/Inicio v3.png", "192.0.2.41", None),
    (58, "ana.garcia", "share_updated", "proyectos", "192.0.2.15", None),
    (95, "carlos.diaz", "login_failed", None, "203.0.113.50", None),
    (96, "carlos.diaz", "login", None, "192.0.2.77", "local"),
    (140, "ana.garcia", "api_token_created", "Portátil (VS Code)", "192.0.2.15", "connect"),
    (300, "javier.moreno@ejemplo.com", "login", None, "198.51.100.40", "entra"),
    (420, "ana.garcia", "user_created", "elena.navarro", "192.0.2.15", None),
    (600, "elena.navarro", "mkdir", "marketing:Redes sociales", "192.0.2.88", None),
    (1500, None, "ip_banned", "203.0.113.50", None, "automatic"),
    (2900, "ana.garcia", "backup_created", "storageweb-backup.tar.gz", "192.0.2.15", None),
    (4300, "ana.garcia", "settings_updated", "general", "192.0.2.15", None),
]


def build(base: Path, port: int) -> Path:
    """Crea la configuración, los ajustes, las cuentas, los archivos y el historial. Devuelve el config.json."""
    from storageweb import create_app
    from storageweb.core import groups as group_core
    from storageweb.core import ipban, tokens
    from storageweb.db.repositories import audit, sessions, users
    from storageweb.db.repositories import groups as group_repo
    from storageweb.settings import store
    from storageweb.web.context import get_db
    from werkzeug.security import generate_password_hash

    data, homes, shares = base / "data", base / "homes", base / "shares"
    shown = SERVER_ROOT  # las rutas que se guardan y se ven; _fake_disk las lleva a la carpeta temporal
    config = base / "config.json"
    config.write_text(json.dumps({
        # Como detrás de un proxy HTTPS: capture.mjs manda X-Forwarded-Proto y la IP del cliente
        "server": {"host": "127.0.0.1", "port": port, "behind_proxy": True, "proxy_hops": 1},
        "data_dir": str(data), "secret_key": "demo-" + "x" * 40,
        "session": {"lifetime_hours": 24, "cookie_secure": True},
    }), encoding="utf-8")

    trees = [(homes / "ana.garcia", HOME_ANA)] + [(shares / name, items) for name, items in SHARES.items()]
    for top, items in trees:
        for rel, size, days in items:
            if size is not None:
                _file(top / rel, size, days)
        # Las carpetas, al final y de dentro afuera: crear archivos dentro les cambiaría la fecha
        for rel, size, days in sorted(items, key=lambda i: -i[0].count("/")):
            if size is None:
                _folder(top / rel, days)
    for user in ("luis.martin", "elena.navarro", "carlos.diaz"):
        _file(homes / user / "Notas.txt", 3 * KB, 7)

    # Sin «users» una carpeta está abierta a todos (como en config.json): las de grupos llevan users=[]
    share = lambda name, label, **kw: {"name": name, "label": label, "path": f"{shown}/shares/{name}", **kw}  # noqa: E731
    doc = {
        "app_name": "StorageWeb", "default_locale": "es",
        "network": {"public_url": "https://archivos.ejemplo.com"},
        "auth": {"entra": {
            "enabled": True, "tenant_id": TENANT, "client_id": CLIENT, "client_secret": "demo-secreto",
            "secret_expires": (NOW + timedelta(days=210)).isoformat(timespec="seconds"),
            "directory_sync_minutes": 0,
            "role_mappings": {"9b4c2e7f-1d8a-4f3b-a6e5-0c7d9f2b1e83": "admin"},
        }},
        "storage": {
            "home_template": f"{shown}/homes/{{username}}", "home_quota_mb": 5120,
            "hidden": ["Thumbs.db", "*.tmp"],
            "shares": [
                share("proyectos", "Proyectos", users=["ana.garcia"], groups=["diseno", "comerciales"], quota_mb=20480),
                share("contabilidad", "Contabilidad", users=[], groups=["contabilidad", "direccion"],
                      read_only_groups=["direccion"]),
                share("plantillas", "Plantillas", users=["*"], read_only_users=["*"]),
                share("marketing", "Marketing", users=[], groups=["comerciales", "diseno"]),
            ],
            "locations": [
                {"name": "nas-oficina", "type": "smb", "label": "NAS de la oficina", "server": "nas.ejemplo.local",
                 "share": "datos", "username": "storageweb", "password": "demo-secreto"},
            ],
            "group_quotas": {"diseno": 10240},
        },
        "maintenance": {"audit_retention_days": 365, "backup_keep": 7},
    }

    app = create_app(str(config))
    with app.app_context():
        conn = get_db()
        # Carpetas, ubicaciones y cuotas van a sus tablas, al final (las cuotas de grupo necesitan los grupos)
        entities = {k: doc["storage"].pop(k) for k in ("shares", "locations", "group_quotas")}
        store.put_doc(conn, "default", doc, "demo")

        ids = {}
        for username, name, email, source, role, extra in USERS:
            extra = dict(extra)
            quota = extra.pop("quota_mb", None)
            pw = generate_password_hash(PASSWORD) if source == "local" else None
            uid = users.create(conn, username=username, source=source, role=role, password_hash=pw,
                               display_name=name, email=email, **extra)
            users.update(conn, uid, locale="es", theme="system", last_login=_ago(hours=len(ids) * 7 + 1),
                         **({"quota_mb": quota} if quota else {}))
            ids[username] = uid
        for name, label, description, source, external, members in GROUPS:
            gid = group_core.create_group(conn, name=name, label=label, description=description, source=source,
                                          external_id=external)
            group = group_repo.get_by_id(conn, gid)
            for member in members:
                if source == "local":
                    group_core.add_member(conn, group, users.get_by_id(conn, ids[member]))
                else:  # los de Entra ID llegan con el inicio de sesión, como en la realidad
                    group_core.sync_external(conn, ids[member], source, [external])
        store.apply_entities(conn, "default", store.read_entities(conn, "default"), entities, "demo")

        for username, agent, ip, hours in (("luis.martin", "Firefox en Windows", "192.0.2.41", 1),
                                           ("marta.lopez@ejemplo.com", "Edge en Windows", "198.51.100.23", 0.2),
                                           ("javier.moreno@ejemplo.com", "Safari en macOS", "198.51.100.40", 5)):
            sid = f"demo-{username}"
            sessions.create(conn, sid, ids[username], ip, agent)
            conn.execute("UPDATE sessions SET created_at = ?, last_seen = ? WHERE id = ?",
                         (_ago(hours=hours + 2), _ago(hours=hours), sid))
        ana = users.get_by_id(conn, ids["ana.garcia"])
        tokens.create(conn, ana, name="Portátil (VS Code)", scope="write", days=365)
        tokens.create(conn, ana, name="Script de copias", scope="read", days=90)

        ipban.allow(conn, "192.0.2.0/24", by="ana.garcia", reason="Oficina central")
        ipban.ban(conn, "203.0.113.0/24", by="ana.garcia", reason="Intentos de acceso repetidos")

        for minutes, username, action, target, ip, detail in sorted(AUDIT, key=lambda a: -a[0]):  # en orden
            audit.log(conn, action, target, username=username, ip=ip, detail=detail)
            conn.execute("UPDATE audit_log SET ts = ? WHERE id = (SELECT MAX(id) FROM audit_log)",
                         (_ago(minutes=minutes),))
        conn.commit()

        from storageweb.core import maintenance
        runtime = app.extensions["storageweb.runtime"]
        maintenance.create_backup(runtime.current(conn), prune=False)
    return config


# --------------------------------------------------------------------------- capturas

def plan(uids: dict) -> list[dict]:
    """Qué se captura. ``js`` se ejecuta antes de la captura (seleccionar filas, abrir el buscador…)."""
    select = ("(names) => names.forEach(n => document.querySelector(`tr.file-row[data-name=\"${n}\"] "
              "input[type=checkbox]`).click())")
    return [
        {"file": "uso/inicio-sesion.webp", "path": "/login?manual=1", "as": None},
        {"file": "uso/explorador.webp", "path": "/f/home/", "as": "ana.garcia",
         "js": f"({select})(['Informe trimestral T3.pdf'])"},
        {"file": "uso/seleccion.webp", "path": "/f/home/", "as": "ana.garcia",
         "js": f"({select})(['Presupuesto 2026.xlsx', 'Notas reunión dirección.docx', 'Plan de proyecto.md'])"},
        {"file": "uso/compartida.webp", "path": "/f/proyectos/", "as": "ana.garcia"},
        {"file": "uso/buscar.webp", "path": "/search?q=presupuesto", "as": "ana.garcia"},
        {"file": "uso/perfil.webp", "path": "/profile", "as": "ana.garcia"},
        {"file": "uso/explorador-oscuro.webp", "path": "/f/home/Documentos/", "as": "ana.garcia", "scheme": "dark"},
        {"file": "uso/movil.webp", "path": "/f/home/", "as": "ana.garcia", "width": 390, "height": 760,
         "mobile": True},
        {"file": "admin/resumen.webp", "path": "/admin/", "as": "ana.garcia"},
        {"file": "admin/buscador.webp", "path": "/admin/", "as": "ana.garcia",
         "js": "(() => { const d = document.getElementById('admin-search'); d.showModal();"
               " const i = d.querySelector('input'); i.value = 'cuota'; i.dispatchEvent(new Event('input')); })()",
         "wait": 900},
        {"file": "admin/usuarios.webp", "path": "/admin/users/", "as": "ana.garcia"},
        {"file": "admin/usuario.webp", "path": f"/admin/users/{uids['marta.lopez@ejemplo.com']}", "as": "ana.garcia"},
        {"file": "admin/grupos.webp", "path": "/admin/groups/", "as": "ana.garcia"},
        {"file": "admin/matriz.webp", "path": "/admin/groups/matrix", "as": "ana.garcia"},
        {"file": "admin/carpetas.webp", "path": "/admin/access/folders", "as": "ana.garcia"},
        {"file": "admin/carpeta.webp", "path": "/admin/access/folders/contabilidad", "as": "ana.garcia"},
        {"file": "admin/inicio-sesion.webp", "path": "/admin/settings/auth", "as": "ana.garcia"},
        {"file": "admin/marca.webp", "path": "/admin/settings/general", "as": "ana.garcia"},
        {"file": "admin/ubicaciones.webp", "path": "/admin/storage/", "as": "ana.garcia"},
        {"file": "admin/copias.webp", "path": "/admin/settings/backups", "as": "ana.garcia"},
        {"file": "admin/ips.webp", "path": "/admin/settings/ips", "as": "ana.garcia"},
        {"file": "admin/sesiones.webp", "path": "/admin/settings/sessions", "as": "ana.garcia"},
        {"file": "admin/auditoria.webp", "path": "/admin/audit", "as": "ana.garcia"},
        {"file": "admin/sistema.webp", "path": "/admin/settings/system", "as": "ana.garcia"},
    ]


def _browser() -> str:
    candidates = [os.environ.get("STORAGEWEB_BROWSER", ""),
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("microsoft-edge") or "", shutil.which("google-chrome") or "",
                  shutil.which("chromium") or ""]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise SystemExit("No encuentro Edge ni Chrome: indica la ruta en STORAGEWEB_BROWSER.")


def _node() -> str:
    """El primer Node 18 o posterior (trae fetch y WebSocket; los viejos ni siquiera cargan el .mjs)."""
    candidates = [os.environ.get("STORAGEWEB_NODE", ""), shutil.which("node") or "",
                  r"C:\Program Files\nodejs26\node.exe", r"C:\Program Files\nodejs\node.exe"]
    for path in candidates:
        if not path or not Path(path).is_file():
            continue
        out = subprocess.run([path, "--version"], capture_output=True, text=True, check=False).stdout.strip()
        if out.startswith("v") and out[1:].split(".")[0].isdigit() and int(out[1:].split(".")[0]) >= 18:
            return path
    raise SystemExit("No encuentro Node 18 o posterior: indica la ruta en STORAGEWEB_NODE.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve", action="store_true", help="solo dejar la demo en marcha (Ctrl+C para salir)")
    ap.add_argument("--port", type=int, default=0, help="puerto (por defecto, uno libre)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "img", help="carpeta de las capturas")
    ap.add_argument("--only", default="", help="solo las capturas cuyo fichero empieza por esto")
    args = ap.parse_args()

    _block_outbound()
    from waitress.server import create_server

    base = Path(tempfile.mkdtemp(prefix="storageweb-demo-"))
    _fake_disk(base)
    try:
        sock = socket.socket()
        sock.bind(("127.0.0.1", args.port))
        port = sock.getsockname()[1]
        sock.close()
        config = build(base, port)

        from storageweb import create_app
        from storageweb.db import connect
        app = create_app(str(config))
        from storageweb.cli.server import waitress_options
        server = create_server(app, host="127.0.0.1", port=port, **waitress_options(app.config["SW"]["server"]))
        threading.Thread(target=server.run, daemon=True).start()
        url = f"http://127.0.0.1:{port}"

        if args.serve:
            print(f"Demo en {url} · usuario ana.garcia, contraseña {PASSWORD} · Ctrl+C para salir")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return 0

        conn = connect(str(base / "data" / "storageweb.db"))
        uids = {r["username"]: r["uid"] for r in conn.execute("SELECT username, uid FROM users")}
        conn.close()
        shots = [s for s in plan(uids) if s["file"].startswith(args.only)]
        plan_file = base / "plan.json"
        # Las rutas de la carpeta temporal (llevan el usuario de este equipo) se ven como las de un servidor
        replace = []
        for real_path, shown_path in ((base / "data", "/var/lib/storageweb"), (base, SERVER_ROOT)):
            for form in (str(real_path), real_path.as_posix()):
                replace.append([form, shown_path])
        replace.append([f"127.0.0.1:{port}", "127.0.0.1:8080"])   # el puerto libre que tocó, como el de serie
        plan_file.write_text(json.dumps({"base": url, "password": PASSWORD, "out": str(args.out), "shots": shots,
                                         "replace": replace}, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([_node(), str(Path(__file__).with_name("capture.mjs")), str(plan_file), _browser()],
                                check=False)
        server.close()
        return result.returncode
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

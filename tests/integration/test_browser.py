"""Tests en un navegador de verdad (Edge o Chrome sin ventana, tests/browser/*.test.mjs) contra un servidor real.

Prueban lo que solo existe en el navegador: el JavaScript de las páginas, la CSP (cualquier error de la consola
falla), el modal propio, cargar más al bajar y el filtro del servidor, el visor con un diagrama Mermaid en su
marco aislado, el editor con Ctrl+S, las imágenes del visor, el buscador Ctrl+K, la barra de guardar de los ajustes y las passkeys
(con un autenticador virtual del navegador, en ``http://localhost``: el único origen sin HTTPS donde se admiten),
también para entrar solo con una.

Hace falta Node 18 o posterior y Edge o Chrome (``STORAGEWEB_BROWSER``). Sin ellos se omite, salvo con
``STORAGEWEB_REQUIRE_BROWSER=1`` (la CI), que entonces falla: así no se deja de probar sin darse cuenta.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tests.helpers import PASSWORD, add_user, update_settings
from tests.integration.test_vscode_extension import NODE

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = os.environ.get("STORAGEWEB_REQUIRE_BROWSER") == "1"


def _browser() -> str | None:
    if not NODE:
        return None
    found = subprocess.run([NODE, "--input-type=module", "-e",
                            "import { findBrowser } from './tools/cdp.mjs'; console.log(findBrowser() || '')"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
    return found.stdout.strip() or None


BROWSER = _browser()
pytestmark = pytest.mark.skipif(not REQUIRED and (NODE is None or BROWSER is None),
                                reason="hace falta Node 18+ y Edge o Chrome (STORAGEWEB_BROWSER)")

MARKDOWN = """# Notas

Texto con **negrita**.

```mermaid
flowchart LR
  A[Subir] --> B[Ver]
```
"""


def _slow_check(rows, timeout=None, progress=None):
    """La comprobación de vulnerabilidades sin salir a internet: avanza por sus fases despacio (para ver la barra y
    dejarla en segundo plano) y devuelve dos bibliotecas, para ordenar la tabla."""
    import time
    for done in range(4):
        progress("versions", done, 3)
        time.sleep(0.6)
    progress("vulnerabilities", 0, 1)
    time.sleep(0.4)
    progress("details", 1, 1)
    row = {"ecosystem": "PyPI", "kind": "Python", "group": "other", "latest": "", "state": "unknown", "url": "",
           "error": "", "vulns": [], "risk": 0}
    return {"at": "2026-11-21T10:00:00+00:00", "checked": 2, "behind": 0, "vulns_ok": True, "vulns_error": "",
            "vuln_asked": 2, "vuln_total": 0, "vuln_packages": 0, "worst": "",
            "rows": [{**row, "name": "zeta", "installed": "1.10.0"}, {**row, "name": "alfa", "installed": "1.9.0"}]}


def test_in_a_real_browser(make_app, home, monkeypatch):
    assert NODE and BROWSER, "STORAGEWEB_REQUIRE_BROWSER=1 pero no hay Node 18+ o un navegador"
    from storageweb.core import advisories
    monkeypatch.setattr(advisories, "check", _slow_check)
    # Entra ID con el directorio simulado: Personas → Importar busca mientras se escribe
    from storageweb.providers.entra import directory as entra_directory
    from tests.integration.test_entra_import import JUAN, PEDRO
    people = {"oid-juan": JUAN, "oid-pedro": PEDRO}
    monkeypatch.setattr(entra_directory, "search_users", lambda ecfg, text, limit=25: [
        u for u in people.values() if u["displayName"].lower().startswith(text.lower())])
    monkeypatch.setattr(entra_directory, "get_user", lambda ecfg, oid: people.get(oid))
    monkeypatch.setattr(entra_directory, "member_groups", lambda ecfg, oid: [])
    monkeypatch.setattr(entra_directory, "assignment", lambda ecfg: {"required": True, "users": {"oid-pedro"}})
    everyone = sorted(people.values(), key=lambda u: u["displayName"])
    monkeypatch.setattr(entra_directory, "list_users", lambda ecfg, skiptoken="", page_size=50: (
        everyone[int(skiptoken or 0):int(skiptoken or 0) + 1],
        str(int(skiptoken or 0) + 1) if int(skiptoken or 0) + 1 < len(everyone) else ""))
    from tests.sso_helpers import entra_cfg
    app = make_app({"storage": {"page_size": 50, "listing_mode": "scroll"},
                    "permissions": {"user": {"edit": True}}, "auth": {"entra": entra_cfg()}})
    app.config["SW_SYNC_JOBS"] = False       # la comprobación de vulnerabilidades en su hilo, como de verdad
    add_user(app, "ana")
    add_user(app, "root", role="admin")
    add_user(app, "pepa")      # la de las passkeys (tests/browser/passkeys.test.mjs)
    many = home / "Muchos"
    many.mkdir(parents=True)
    for i in range(120):
        (many / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
    (home / "notas.md").write_text(MARKDOWN, encoding="utf-8")
    (home / "texto.txt").write_text("primera línea\n", encoding="utf-8")
    (home / "borrar.txt").write_text("x", encoding="utf-8")
    from tests.integration.test_viewer_media import PNG
    (home / "foto.png").write_bytes(PNG)
    (home / "script.py").write_text('def saluda(nombre):\n    """Varias\n    líneas"""\n    return f"hola {nombre}"  # fin\n',
                                    encoding="utf-8", newline="\n")      # LF también en Windows

    from waitress.server import create_server
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    # Las passkeys se atan al nombre de network.public_url: localhost, que el navegador admite sin HTTPS
    update_settings(app, network={"public_url": f"http://localhost:{port}"}, security={"passkey_login": True})
    server = create_server(app, host="127.0.0.1", port=port, threads=4)
    threading.Thread(target=server.run, daemon=True).start()
    try:
        env = {**os.environ, "STORAGEWEB_TEST_URL": f"http://127.0.0.1:{port}", "STORAGEWEB_TEST_PASSWORD": PASSWORD,
               "STORAGEWEB_TEST_LOCALHOST_URL": f"http://localhost:{port}",
               "STORAGEWEB_BROWSER": BROWSER}
        tests = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests" / "browser").glob("*.test.mjs"))
        result = subprocess.run([NODE, "--test", "--test-concurrency=1", *tests], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=600)
    finally:
        server.close()
    output = result.stdout[-6000:] + result.stderr[-3000:]
    if result.returncode != 0:
        sys.stderr.write(output)
    assert result.returncode == 0, output
    assert "fail 0" in result.stdout and "skipped 0" in result.stdout, output   # nada se omite
    assert (home / "texto.txt").read_text(encoding="utf-8") == "primera línea\nañadida desde el navegador\n"
    assert (home / "subido.txt").read_text(encoding="utf-8") == "subido desde el navegador\n"   # files/upload.js

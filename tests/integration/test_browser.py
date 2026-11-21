"""Tests en un navegador de verdad (Edge o Chrome sin ventana, tests/browser/*.test.mjs) contra un servidor real.

Prueban lo que solo existe en el navegador: el JavaScript de las páginas, la CSP (cualquier error de la consola
falla), el modal propio, cargar más al bajar y el filtro del servidor, el visor con un diagrama Mermaid en su
marco aislado, el editor con Ctrl+S, el buscador Ctrl+K, la barra de guardar de los ajustes y las passkeys (con un
autenticador virtual del navegador, en ``http://localhost``: el único origen sin HTTPS donde se admiten).

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


def test_in_a_real_browser(make_app, home):
    assert NODE and BROWSER, "STORAGEWEB_REQUIRE_BROWSER=1 pero no hay Node 18+ o un navegador"
    app = make_app({"storage": {"page_size": 50, "listing_mode": "scroll"},
                    "permissions": {"user": {"edit": True}}})
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
    (home / "script.py").write_text('def saluda(nombre):\n    """Varias\n    líneas"""\n    return f"hola {nombre}"  # fin\n',
                                    encoding="utf-8", newline="\n")      # LF también en Windows

    from waitress.server import create_server
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    # Las passkeys se atan al nombre de network.public_url: localhost, que el navegador admite sin HTTPS
    update_settings(app, network={"public_url": f"http://localhost:{port}"})
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

"""Extensión de VS Code (clients/vscode): sus tests de Node, y la sincronización contra un servidor real.

Se omite si no hay Node 18 o posterior (``STORAGEWEB_NODE`` o ``node`` en el PATH).
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from storageweb.core import tokens
from storageweb.db.repositories import users
from storageweb.web.context import get_db

from tests.helpers import PASSWORD, add_user

EXTENSION = Path(__file__).resolve().parents[2] / "clients" / "vscode"


def _node() -> str | None:
    for candidate in (os.environ.get("STORAGEWEB_NODE"), shutil.which("node"),
                      r"C:\Program Files\nodejs26\node.exe", r"C:\Program Files\nodejs\node.exe"):
        if not candidate or not Path(candidate).exists() and not shutil.which(candidate):
            continue
        try:
            version = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=10).stdout
        except OSError:
            continue
        if version.startswith("v") and int(version[1:].split(".")[0]) >= 18:
            return candidate
    return None


NODE = _node()
pytestmark = pytest.mark.skipif(NODE is None, reason="hace falta Node 18 o posterior")


def test_extension_against_a_real_server(make_app, tmp_path):
    app = make_app({"storage": {"hidden": ["*.oculto"]}})
    add_user(app, "ana")
    with app.app_context():
        plain, _id = tokens.create(get_db(), users.get_by_username(get_db(), "ana"), name="vscode", scope="write",
                                   days=0)
    from waitress.server import create_server
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = create_server(app, host="127.0.0.1", port=port, threads=4)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        env = {**os.environ, "STORAGEWEB_TEST_URL": f"http://127.0.0.1:{port}", "STORAGEWEB_TEST_USER": "ana",
               "STORAGEWEB_TEST_TOKEN": plain, "STORAGEWEB_TEST_PASSWORD": PASSWORD, "STORAGEWEB_TEST_DATA": str(tmp_path / "data"), "STORAGEWEB_TEST_HIDDEN": "*.oculto"}
        # Los ficheros, no la carpeta: desde Node 22 un directorio como argumento de --test no se recorre
        tests = sorted(p.relative_to(EXTENSION).as_posix() for p in (EXTENSION / "test").glob("*.test.js"))
        result = subprocess.run([NODE, "--test", *tests], cwd=EXTENSION, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=300)
    finally:
        server.close()
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# skipped 0" in result.stdout or "skipped 0" in result.stdout

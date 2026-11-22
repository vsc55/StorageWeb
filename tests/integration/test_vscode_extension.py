"""Extensión de VS Code (clients/vscode): sus tests de Node, y la sincronización contra un servidor real.

Se omite si no hay Node 18 o posterior (``STORAGEWEB_NODE`` o ``node`` en el PATH).
"""
from __future__ import annotations

import os
import subprocess

import pytest

from tests.helpers import PASSWORD, ROOT, add_user, api_token, node, serve_in_thread

EXTENSION = ROOT / "clients" / "vscode"
NODE = node()
pytestmark = pytest.mark.skipif(NODE is None, reason="hace falta Node 18 o posterior")


def test_extension_against_a_real_server(make_app, tmp_path):
    app = make_app({"storage": {"hidden": ["*.oculto"]}})
    add_user(app, "ana")
    plain = api_token(app, name="vscode")
    with serve_in_thread(app) as port:
        env = {**os.environ, "STORAGEWEB_TEST_URL": f"http://127.0.0.1:{port}", "STORAGEWEB_TEST_USER": "ana",
               "STORAGEWEB_TEST_TOKEN": plain, "STORAGEWEB_TEST_PASSWORD": PASSWORD, "STORAGEWEB_TEST_DATA": str(tmp_path / "data"), "STORAGEWEB_TEST_HIDDEN": "*.oculto"}
        # Los ficheros, no la carpeta: desde Node 22 un directorio como argumento de --test no se recorre
        tests = sorted(p.relative_to(EXTENSION).as_posix() for p in (EXTENSION / "test").glob("*.test.js"))
        result = subprocess.run([NODE, "--test", *tests], cwd=EXTENSION, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# skipped 0" in result.stdout or "skipped 0" in result.stdout

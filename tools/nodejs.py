"""Buscar Node.js y el navegador (Edge o Chrome) de este equipo, para lo que se lanza con Node: las capturas de la
documentación (tools/screenshots/demo.py) y los tests de la extensión de VS Code y del navegador.

Node: ``STORAGEWEB_NODE``, el del PATH o los sitios de siempre en Windows. El navegador lo busca ``findBrowser`` de
tools/cdp.mjs (``STORAGEWEB_BROWSER`` o las rutas habituales), para no tener la lista dos veces.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = (r"C:\Program Files\nodejs26\node.exe", r"C:\Program Files\nodejs\node.exe")


def node_major(path: str) -> int | None:
    """La versión principal de ese Node (``v22.1.0`` → 22), o ``None`` si no arranca."""
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    out = out.strip()
    major = out[1:].split(".")[0] if out.startswith("v") else ""
    return int(major) if major.isdigit() else None


def find_node(min_major: int = 18) -> str | None:
    """El primer Node ``min_major`` o posterior (desde el 18 trae fetch y WebSocket), o ``None``."""
    for candidate in (os.environ.get("STORAGEWEB_NODE"), shutil.which("node"), *CANDIDATES):
        if not candidate or not Path(candidate).exists() and not shutil.which(candidate):
            continue
        major = node_major(candidate)
        if major is not None and major >= min_major:
            return candidate
    return None


def find_browser(node: str | None = None) -> str | None:
    """El navegador que encuentra ``findBrowser`` de tools/cdp.mjs (con ``node`` o el de :func:`find_node`)."""
    node = node or find_node()
    if not node:
        return None
    found = subprocess.run([node, "--input-type=module", "-e",
                            "import { findBrowser } from './tools/cdp.mjs'; console.log(findBrowser() || '')"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
    return found.stdout.strip() or None

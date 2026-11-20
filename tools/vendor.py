"""Bibliotecas de JavaScript del navegador copiadas en el paquete (``src/storageweb/web/static/vendor/``).

Sin npm ni pnpm: descarga del registro de npm el paquete de una **versión fija**, comprueba su huella SHA-512
(la del registro, fijada aquí) y extrae solo los ficheros que se usan. No ejecuta nada del paquete. Los
ficheros extraídos se guardan en el repositorio, y su SHA-256 también está aquí: ``--check`` los comprueba sin
red (lo hacen los tests y la CI), así que un cambio a mano en ``static/vendor/`` no pasa desapercibido.

    python tools/vendor.py            # descarga y extrae lo que falte o no coincida
    python tools/vendor.py --check    # solo comprueba (sin red)

Para actualizar una biblioteca: cambia ``version``, ``tarball`` e ``integrity`` (``https://registry.npmjs.org/
<paquete>/<versión>`` → ``dist``), vacía ``sha256``, ejecútalo, copia las huellas que imprime y revisa el
CHANGELOG de la biblioteca. Mejor una versión con al menos dos semanas.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src" / "storageweb" / "web" / "static" / "vendor"

PACKAGES = {
    # Diagramas de los .md en el visor; se ejecuta solo dentro de un marco aislado (web/views/files.py, diagram)
    "mermaid": {
        "version": "12.3.0",
        "tarball": "https://registry.npmjs.org/mermaid/-/mermaid-12.3.0.tgz",
        "integrity": "sha512-4113TdXeLAsMruJ79OpFL5O8+LTFXhQqZ260rF3tgUmiNAtRm4Uume04I+65PRN6yZ69J4f8rVYWW8zRk65UYw==",
        "files": {"package/dist/mermaid.min.js": "mermaid/mermaid.min.js", "package/LICENSE": "mermaid/LICENSE"},
        "sha256": {"mermaid/mermaid.min.js": "336df803d87a38b70a01e736e666c8f7601d2ce42f5e47c8fafe5d721074b9a3",
                   "mermaid/LICENSE": "ec9fb67dcb25eccc416ed56e1aab819222c805a2a4bfe4cb19e7556bf2ffde80"},
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check() -> list[str]:
    """Ficheros que faltan o no coinciden con su huella."""
    problems = []
    for name, pkg in PACKAGES.items():
        for out in pkg["files"].values():
            path = VENDOR / out
            expected = pkg["sha256"].get(out)
            if not path.is_file():
                problems.append(f"{name}: falta {out}")
            elif not expected or _sha256(path) != expected:
                problems.append(f"{name}: {out} no coincide con su huella")
    return problems


def fetch(name: str, pkg: dict) -> None:
    request = urllib.request.Request(pkg["tarball"], headers={"User-Agent": "storageweb-vendor"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        data = resp.read()
    algorithm, _, wanted = pkg["integrity"].partition("-")
    got = base64.b64encode(hashlib.new(algorithm, data).digest()).decode()
    if got != wanted:
        raise SystemExit(f"{name} {pkg['version']}: la huella del paquete no coincide; no se usa")
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for member, out in pkg["files"].items():
            source = tf.extractfile(member)
            if source is None:
                raise SystemExit(f"{name}: el paquete no trae {member}")
            target = VENDOR / out
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            print(f"{name} {pkg['version']}: {out}  sha256 {_sha256(target)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="solo comprobar las huellas, sin red")
    args = parser.parse_args()
    if not args.check:
        for name, pkg in PACKAGES.items():
            if any(p.startswith(f"{name}:") for p in check()):
                fetch(name, pkg)
    problems = check()
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("Bibliotecas de static/vendor/ correctas.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Bibliotecas de JavaScript del navegador copiadas en el paquete (``src/storageweb/web/static/vendor/``).

Sin npm ni pnpm: descarga del registro de npm el paquete de una **versión fija**, comprueba su huella SHA-512
(la del registro, fijada aquí) y extrae solo los ficheros que se usan. No ejecuta nada del paquete. Los
ficheros extraídos se guardan en el repositorio, y su SHA-256 también está aquí: ``--check`` los comprueba sin
red (lo hacen los tests y la CI), así que un cambio a mano en ``static/vendor/`` no pasa desapercibido.

    python tools/vendor.py              # descarga y extrae lo que falte o no coincida
    python tools/vendor.py --check      # solo comprueba (sin red)
    python tools/vendor.py --outdated   # ¿versión nueva o avisos de seguridad? (registro de npm; sale con 3 si hay)

``--outdated`` lo ejecuta cada semana la CI (``.github/workflows/vendor.yml``), que abre o actualiza un aviso en
GitHub: una versión estable más nueva con al menos :data:`MIN_AGE_DAYS` días (lo que se publica hoy espera, por si
lo retiran o trae un fallo) y los avisos de seguridad que afectan a la versión fijada (de la API de avisos del
registro de npm), que se señalan aunque no haya versión nueva. Imprime lo que hay que poner para actualizar.

Para actualizar una biblioteca: cambia ``version``, ``tarball`` e ``integrity`` (``https://registry.npmjs.org/
<paquete>/<versión>`` → ``dist``), vacía ``sha256``, ejecútalo, copia las huellas que imprime y revisa el
CHANGELOG de la biblioteca. Mejor una versión con al menos dos semanas.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src" / "storageweb" / "web" / "static" / "vendor"
# Qué hay copiado, para el propio StorageWeb (Sistema → Información, core/diagnostics.vendored): nombre, versión, el
# ajuste que lo usa y la huella de cada fichero. Lo escribe este programa y --check lo compara
MANIFEST = VENDOR / "vendor.json"
REGISTRY = "https://registry.npmjs.org"
MIN_AGE_DAYS = 14
OUTDATED = 3       # código de salida de --outdated cuando hay algo que mirar

PACKAGES = {
    # Diagramas de los .md en el visor; se ejecuta solo dentro de un marco aislado (web/views/files.py, diagram)
    "mermaid": {
        "setting": "preview.diagrams",
        "version": "12.3.0",
        "tarball": "https://registry.npmjs.org/mermaid/-/mermaid-12.3.0.tgz",
        "integrity": "sha512-4113TdXeLAsMruJ79OpFL5O8+LTFXhQqZ260rF3tgUmiNAtRm4Uume04I+65PRN6yZ69J4f8rVYWW8zRk65UYw==",
        "files": {"package/dist/mermaid.min.js": "mermaid/mermaid.min.js", "package/LICENSE": "mermaid/LICENSE"},
        "sha256": {"mermaid/mermaid.min.js": "336df803d87a38b70a01e736e666c8f7601d2ce42f5e47c8fafe5d721074b9a3",
                   "mermaid/LICENSE": "ec9fb67dcb25eccc416ed56e1aab819222c805a2a4bfe4cb19e7556bf2ffde80"},
    },
    # Colores del código en el visor (viewer.js): el paquete preparado para el navegador, con los lenguajes comunes
    # y unos pocos más que suelen estar en un servidor de archivos
    "highlight.js": {
        "registry": "@highlightjs/cdn-assets",
        # Los avisos de seguridad (OSV, npm) se publican para «highlight.js», el mismo código
        "advisories": "highlight.js",
        "setting": "preview.highlight",
        "version": "11.12.0",
        "tarball": "https://registry.npmjs.org/@highlightjs/cdn-assets/-/cdn-assets-11.12.0.tgz",
        "integrity": "sha512-KvOKXODaiFmId9xaq3xc5xCL66wVLUuOngDbO9B/kewbFTqdGbn2nJxNhN3H5R1cgDTVj6R8vH0zgiNDEGjpDw==",
        "files": {"package/highlight.min.js": "highlight/highlight.min.js", "package/LICENSE": "highlight/LICENSE",
                  **{f"package/languages/{lang}.min.js": f"highlight/languages/{lang}.min.js"
                     for lang in ("apache", "dockerfile", "dos", "nginx", "powershell", "vbscript")}},
        "sha256": {
            "highlight/highlight.min.js": "8ab71eb09c51f501e5e25157d9cff100e46cc29bcbfc744d0b746d451fca7f53",
            "highlight/LICENSE": "6c081431591d9df696c82dc598fe1423765b8a299b200ed00b281afd0f64c490",
            "highlight/languages/apache.min.js": "9dc53948535832b25d4eb23d40fef70510317398fdaf15f8a3fcc3ae7e0c490c",
            "highlight/languages/dockerfile.min.js": "d96f73b077d654d776795097cf49afae5dce3ce453106af022eae013ad2ec8b1",
            "highlight/languages/dos.min.js": "e184a6f9cead550b7b39b6114d17cafd08904557317622d7ea488aed01cf31ee",
            "highlight/languages/nginx.min.js": "8c53cc63ce0cf4ec0ad80b77273de23dec6974ab069d46d14d5c75febe880e1f",
            "highlight/languages/powershell.min.js": "fc298b3e0db362e531e6d58988b7a78f83da19df6b5d74db75bc961b2bfbfd3d",
            "highlight/languages/vbscript.min.js": "2bcde5a79ac8d9253b7455bac11a79288e3fc1594bc342d697048d65c2c14f38",
        },
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest() -> str:
    """El contenido de vendor.json para lo fijado aquí (estable: claves en orden y salto de línea final)."""
    data = {name: {"package": pkg.get("registry", name), "advisories": pkg.get("advisories", pkg.get("registry", name)),
                   "version": pkg["version"], "setting": pkg.get("setting", ""),
                   "files": dict(sorted(pkg["sha256"].items()))}
            for name, pkg in sorted(PACKAGES.items())}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def check() -> list[str]:
    """Ficheros que faltan o no coinciden con su huella, y vendor.json si no dice lo fijado aquí."""
    problems = []
    if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != manifest():
        problems.append("vendor.json no coincide con lo fijado en tools/vendor.py")
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


def _http_json(url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "storageweb-vendor",
                                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.loads(resp.read())


def _version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("-")[0].split("."))


def outdated(get_json: Callable = _http_json, now: datetime | None = None) -> list[dict]:
    """Lo que hay que mirar de cada biblioteca: ``{name, current, latest, published, tarball, integrity,
    advisories}`` si hay una versión estable más nueva con al menos MIN_AGE_DAYS días o avisos de seguridad que
    afectan a la fijada."""
    now = now or datetime.now(timezone.utc)
    found = []
    for name, pkg in PACKAGES.items():
        package = pkg.get("registry", name)       # el nombre en el registro (con ámbito: @x/y)
        doc = get_json(f"{REGISTRY}/{package.replace('/', '%2F')}")
        latest = doc.get("dist-tags", {}).get("latest", pkg["version"])
        published = doc.get("time", {}).get(latest, "")
        when = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else now
        newer = (_version_key(latest) > _version_key(pkg["version"])
                 and now - when >= timedelta(days=MIN_AGE_DAYS))
        report = get_json(f"{REGISTRY}/-/npm/v1/security/advisories/bulk", {package: [pkg["version"]]}) or {}
        advisories = [{"title": a.get("title", ""), "severity": a.get("severity", ""), "url": a.get("url", ""),
                       "vulnerable": a.get("vulnerable_versions", "")} for a in report.get(package, [])]
        if newer or advisories:
            dist = doc.get("versions", {}).get(latest, {}).get("dist", {}) if newer else {}
            found.append({"name": name, "current": pkg["version"], "latest": latest if newer else "",
                          "published": published if newer else "", "tarball": dist.get("tarball", ""),
                          "integrity": dist.get("integrity", ""), "advisories": advisories})
    return found


def report(found: list[dict]) -> str:
    """El resultado en Markdown (el cuerpo del aviso de GitHub)."""
    if not found:
        return "Las bibliotecas de `static/vendor/` están al día y sin avisos de seguridad."
    lines = []
    for item in found:
        lines.append(f"## {item['name']} {item['current']}")
        for adv in item["advisories"]:
            lines.append(f"- **Aviso de seguridad ({adv['severity']})**: [{adv['title']}]({adv['url']}) "
                         f"— afecta a `{adv['vulnerable']}`")
        if item["latest"]:
            lines.append(f"- Versión nueva: **{item['latest']}** (publicada {item['published'][:10]}). En "
                         "`tools/vendor.py`, pon:")
            lines += ["  ```python",
                      f'  "version": "{item["latest"]}",',
                      f'  "tarball": "{item["tarball"]}",',
                      f'  "integrity": "{item["integrity"]}",',
                      "  ```",
                      "  vacía `sha256`, ejecuta `python tools/vendor.py`, copia las huellas que imprime y revisa "
                      "el CHANGELOG de la biblioteca."]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="solo comprobar las huellas, sin red")
    parser.add_argument("--outdated", action="store_true",
                        help="buscar versiones nuevas y avisos de seguridad en el registro de npm")
    args = parser.parse_args()
    if args.outdated:
        found = outdated()
        print(report(found))
        return OUTDATED if found else 0
    if not args.check:
        for name, pkg in PACKAGES.items():
            if any(p.startswith(f"{name}:") for p in check()):
                fetch(name, pkg)
        MANIFEST.write_text(manifest(), encoding="utf-8", newline="\n")
    problems = check()
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("Bibliotecas de static/vendor/ correctas.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

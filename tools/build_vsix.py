#!/usr/bin/env python3
"""Empaqueta la extensión de VS Code (clients/vscode) en un .vsix sin npm ni vsce.

    python tools/build_vsix.py                    -> clients/vscode/dist/storageweb-sync-<versión>.vsix
    python tools/build_vsix.py --version 1.2.0 --out dist   (la release: la versión de StorageWeb)
    python tools/build_vsix.py --install          -> además lo instala en VS Code (``code --install-extension``)

Un .vsix es un zip (formato OPC) con ``extension.vsixmanifest``, ``[Content_Types].xml`` y la
extensión dentro de ``extension/``. Se instala en VS Code con *Extensiones → ⋯ → Instalar desde VSIX…*
o ``code --install-extension <fichero>.vsix``.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "clients" / "vscode"
# Lo que va en el paquete (los tests y la carpeta dist, no)
INCLUDE = ("package.json", "package.nls.json", "package.nls.*.json", "README.md", "CHANGELOG.md", "src/*.js",
           "l10n/*.json", "media/*.svg")
CONTENT_TYPES = {".json": "application/json", ".js": "application/javascript", ".md": "text/markdown",
                 ".svg": "image/svg+xml", ".vsixmanifest": "text/xml"}


def files() -> list[Path]:
    found: list[Path] = []
    for pattern in INCLUDE:
        found += sorted(EXTENSION.glob(pattern))
    return found


def manifest(pkg: dict, nls: dict) -> str:
    def text(value: str) -> str:  # «%clave%» → el texto en inglés de package.nls.json
        return nls.get(value[1:-1], value) if value.startswith("%") and value.endswith("%") else value
    langs = sorted(p.stem.split(".")[-1] for p in EXTENSION.glob("package.nls.*.json"))
    props = {
        "Microsoft.VisualStudio.Code.Engine": pkg["engines"]["vscode"],
        "Microsoft.VisualStudio.Code.ExtensionDependencies": "",
        "Microsoft.VisualStudio.Code.ExtensionPack": "",
        "Microsoft.VisualStudio.Code.ExtensionKind": "workspace",
        "Microsoft.VisualStudio.Code.LocalizedLanguages": ",".join(langs),
        "Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown": "true",
    }
    properties = "\n".join(f'      <Property Id="{k}" Value="{escape(v)}" />' for k, v in props.items())
    return f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{escape(pkg["name"])}" Version="{escape(pkg["version"])}" Publisher="{escape(pkg["publisher"])}" />
    <DisplayName>{escape(text(pkg["displayName"]))}</DisplayName>
    <Description xml:space="preserve">{escape(text(pkg["description"]))}</Description>
    <Tags>{escape(",".join(pkg.get("keywords", [])))}</Tags>
    <Categories>{escape(",".join(pkg.get("categories", [])))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
{properties}
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />
  </Assets>
</PackageManifest>
'''


def content_types() -> str:
    defaults = "".join(f'<Default Extension="{ext}" ContentType="{ctype}" />' for ext, ctype in CONTENT_TYPES.items())
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">{defaults}</Types>\n')


def build(out_dir: Path, version: str | None = None) -> Path:
    pkg = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
    nls = json.loads((EXTENSION / "package.nls.json").read_text(encoding="utf-8"))
    if version:
        if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", version):
            raise SystemExit(f"Versión no válida: {version!r} (X.Y.Z o X.Y.Z-sufijo)")
        pkg["version"] = version
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{pkg['name']}-{pkg['version']}.vsix"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types())
        zf.writestr("extension.vsixmanifest", manifest(pkg, nls))
        for path in files():
            if path.suffix not in CONTENT_TYPES:
                raise SystemExit(f"Tipo de archivo sin Content-Type en el paquete: {path}")
            name = "extension/" + path.relative_to(EXTENSION).as_posix()
            if name == "extension/package.json":  # con la versión elegida
                zf.writestr(name, json.dumps(pkg, ensure_ascii=False, indent=2) + "\n")
            else:
                zf.write(path, name)
    return target


def install(target: Path, code: str | None = None) -> int:
    """Instala el .vsix con la línea de comandos de VS Code (``code``, o la que se indique)."""
    cli = code or shutil.which("code") or shutil.which("code-insiders")
    if not cli:
        print("No encuentro la orden «code» de VS Code en el PATH. Instálalo a mano:\n"
              f"  code --install-extension \"{target}\"\n"
              "o en VS Code: Extensiones → ⋯ → Instalar desde VSIX…", file=sys.stderr)
        return 1
    try:
        result = subprocess.run([cli, "--install-extension", str(target), "--force"], check=False)
    except OSError as exc:
        print(f"No se puede ejecutar «{cli}»: {exc}", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"«{cli} --install-extension» falló (código {result.returncode}).", file=sys.stderr)
        return result.returncode
    print("Instalada. Si VS Code ya estaba abierto, recarga la ventana para usarla: "
          "Ctrl+Shift+P → Developer: Reload Window (Desarrollador: Recargar ventana).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=EXTENSION / "dist", help="carpeta de salida")
    parser.add_argument("--version", help="versión del paquete (por defecto, la de package.json)")
    parser.add_argument("--install", action=argparse.BooleanOptionalAction, default=False,
                        help="instalarlo en VS Code al terminar (con «code --install-extension»)")
    parser.add_argument("--code", help="la orden de VS Code para instalar (por defecto, «code» del PATH)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # consolas que no son UTF-8: «→» no rompe la salida
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    target = build(args.out, args.version)
    print(f"{target} ({target.stat().st_size // 1024} KB, {len(files())} archivos)")
    return install(target, args.code) if args.install else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Genera el overlay de Gentoo de una release.

    python3 packaging/gentoo/make_overlay.py --version 1.2.0 \\
        --homepage https://github.com/ORG/storageweb --tarball dist/storageweb-1.2.0.tar.gz \\
        --output dist/storageweb-gentoo-overlay-1.2.0.tar.gz

Crea www-apps/storageweb/storageweb-<pv>.ebuild a partir de storageweb.ebuild.in y su Manifest
(thin-manifests: solo la entrada DIST con BLAKE2B y SHA512 del tarball).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PRE = {"alpha": "alpha", "a": "alpha", "beta": "beta", "b": "beta", "rc": "rc", "pre": "pre", "p": "p"}


def gentoo_version(version: str) -> str:
    """1.2.0 -> 1.2.0 ; 1.2.0-rc1 -> 1.2.0_rc1 ; 1.2.0-beta.2 -> 1.2.0_beta2."""
    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-([a-z]+)\.?(\d*))?", version)
    if not m or (m.group(2) and m.group(2) not in _PRE):
        raise ValueError(f"Versión no representable en Gentoo: {version}")
    base, tag, num = m.groups()
    return f"{base}_{_PRE[tag]}{num}" if tag else base


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:  # LF también en Windows
        fh.write(text)


def manifest_line(tarball: Path) -> str:
    data = tarball.read_bytes()
    return (f"DIST {tarball.name} {len(data)} BLAKE2B {hashlib.blake2b(data).hexdigest()} "
            f"SHA512 {hashlib.sha512(data).hexdigest()}\n")


def build(version: str, homepage: str, license_: str, tarball: Path, output: Path) -> Path:
    pv = gentoo_version(version)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "storageweb-overlay"
        shutil.copytree(HERE, root, ignore=shutil.ignore_patterns("*.py", "__pycache__", "*.in"))
        pkg = root / "www-apps" / "storageweb"
        template = (HERE / "www-apps" / "storageweb" / "storageweb.ebuild.in").read_text(encoding="utf-8")
        # Se quita el comentario inicial de la plantilla (todo lo anterior a EAPI)
        ebuild = template[template.index("EAPI="):]
        ebuild = (ebuild.replace("@VERSION@", version).replace("@HOMEPAGE@", homepage.rstrip("/"))
                  .replace("@GENTOO_LICENSE@", license_))
        header = "# Copyright StorageWeb\n# Generado por packaging/gentoo/make_overlay.py\n\n"
        _write(pkg / f"storageweb-{pv}.ebuild", header + ebuild.rstrip("\n") + "\n")
        _write(pkg / "Manifest", manifest_line(tarball))
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz") as tar:
            tar.add(root, arcname=root.name)
    return output


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--homepage", required=True)
    ap.add_argument("--license", default="GPL-3+")
    ap.add_argument("--tarball", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        out = build(args.version, args.homepage, args.license, args.tarball, args.output)
    except ValueError as exc:
        print(f"AVISO: {exc}; no se genera el overlay de Gentoo", file=sys.stderr)
        return 0
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

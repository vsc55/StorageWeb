"""Lista de contraseñas comunes que rechaza ``security.password_check`` (``providers/local/common_passwords.txt``).

Sale de SecLists (Daniel Miessler y colaboradores, licencia MIT), descargada de un **commit fijo** y comprobada con su
SHA-256: las más usadas de las filtraciones (Pwdb, por frecuencia) y la lista corta en castellano. Solo las que
llegan a la longitud mínima (``MIN_PASSWORD_LENGTH``): las más cortas ya las rechaza la longitud. En minúsculas, sin
repetir y en orden. El resultado se guarda en el repositorio y su SHA-256 también está aquí: ``--check`` lo comprueba
sin red (lo hace un test).

    python tools/common_passwords.py            # descarga, filtra y escribe la lista
    python tools/common_passwords.py --check    # solo comprueba la guardada (sin red)

Para actualizarla: cambia ``COMMIT`` (mejor uno con al menos dos semanas), vacía los ``sha256``, ejecútalo y copia las
huellas que imprime.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from storageweb.providers.local import COMMON_PASSWORDS_FILE, MIN_PASSWORD_LENGTH  # noqa: E402

COMMIT = "00f80ec9cc39bed63ee40cf6805a6b1b77e87644"     # SecLists, 31-10-2026
BASE = f"https://raw.githubusercontent.com/danielmiessler/SecLists/{COMMIT}/Passwords/Common-Credentials/"
SOURCES = [
    # (ruta, cuántas de las primeras se miran, SHA-256 del fichero descargado)
    ("Pwdb_top-1000000.txt", 200_000, "e9a88f67aafe65496682dc374559ee714e978bee50314767494c3e37a18c9fc8"),
    ("Language-Specific/Spanish_Pwdb_common-password-list-top-150.txt", None,
     "46cda56105d02a06a02155619a62eed89f2c4879bea45828907bcea3a6ec7a72"),
]
OUTPUT_SHA256 = "033b5f9223afb728f0e765b58f10f914a0305473ede8f810a9537d175d9f6eff"
HEADER = (f"# Contraseñas comunes que rechaza security.password_check. Generada por tools/common_passwords.py\n"
          f"# desde SecLists (licencia MIT, https://github.com/danielmiessler/SecLists, commit {COMMIT}).\n"
          f"# Solo las de {MIN_PASSWORD_LENGTH} caracteres o más, en minúsculas. No la edites a mano.\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build() -> bytes:
    found: set[str] = set()
    for path, first, digest in SOURCES:
        with urllib.request.urlopen(BASE + path, timeout=60) as resp:   # noqa: S310 (URL fija, de arriba)
            data = resp.read()
        got = _sha256(data)
        if got != digest:
            sys.exit(f"{path}: SHA-256 {got}, se esperaba {digest}")
        lines = data.decode("utf-8", errors="replace").splitlines()
        for line in lines[:first] if first else lines:
            word = line.strip().lower()
            if len(word) >= MIN_PASSWORD_LENGTH and "�" not in word:
                found.add(word)
    return (HEADER + "\n".join(sorted(found)) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="solo comprobar la lista guardada (sin red)")
    args = parser.parse_args()
    if args.check:
        got = _sha256(COMMON_PASSWORDS_FILE.read_bytes()) if COMMON_PASSWORDS_FILE.exists() else "(no existe)"
        if got != OUTPUT_SHA256:
            print(f"{COMMON_PASSWORDS_FILE}: SHA-256 {got}, se esperaba {OUTPUT_SHA256}")
            return 1
        print("La lista de contraseñas comunes coincide.")
        return 0
    data = build()
    COMMON_PASSWORDS_FILE.write_bytes(data)
    print(f"{COMMON_PASSWORDS_FILE}: {data.count(b'\n') - HEADER.count(chr(10))} contraseñas, SHA-256 {_sha256(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Arranque del servicio de Windows: lo ejecuta el intérprete base con ``-S -I`` (ver ``cli/service.py``).

Solo usa la biblioteca estándar hasta añadir las rutas del venv (``--path``, con sus ``.pth``); después
pasa a ``service_host.run``. Ejecutarlo a mano no sirve: fuera del Administrador de servicios lo dice y
termina.
"""
import argparse
import site
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="storageweb-service")
    parser.add_argument("--name", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    for path in args.path:
        site.addsitedir(path)
    from storageweb.cli import service_host

    return service_host.run(args.name, args.config)


if __name__ == "__main__":
    sys.exit(main())

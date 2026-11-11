#!/usr/bin/env python3
"""Arranca StorageWeb con Waitress (servidor WSGI de producción, funciona en Linux, Windows y macOS).

Uso:
    python run.py [--config /etc/storageweb/config.json] [--host 0.0.0.0] [--port 8080]
"""
import argparse
import logging
import sys

from waitress import serve

from src import create_app
from src.config import ConfigError


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor web StorageWeb")
    parser.add_argument("--config", help="Ruta a config.json (por defecto $STORAGEWEB_CONFIG)")
    parser.add_argument("--host", help="Sobrescribe server.host")
    parser.add_argument("--port", type=int, help="Sobrescribe server.port")
    args = parser.parse_args()

    try:
        app = create_app(args.config)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2

    srv = app.config["SW"]["server"]
    host = args.host or srv["host"]
    port = args.port or srv["port"]
    logging.getLogger("waitress").setLevel(logging.INFO)
    app.logger.info("StorageWeb escuchando en http://%s:%s (config: %s)",
                    host, port, app.config["SW"]["_config_path"])
    serve(
        app,
        host=host,
        port=port,
        threads=int(srv["threads"]),
        max_request_body_size=int(srv["max_upload_mb"]) * 1024 * 1024 + 1024 * 1024,
        channel_timeout=300,
        ident="StorageWeb",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

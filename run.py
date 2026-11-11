#!/usr/bin/env python3
"""Arranca StorageWeb.

Producción (Waitress, servidor WSGI multiplataforma):
    python run.py [--config /etc/storageweb/config.json] [--host 0.0.0.0] [--port 8080]

Desarrollo (servidor de Flask con recarga automática al modificar código o config):
    python run.py --dev --config config/config.dev.json [--no-reload]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src import create_app
from src.config import ConfigError, default_config_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor web StorageWeb")
    parser.add_argument("--config", help="Ruta a config.json (por defecto $STORAGEWEB_CONFIG)")
    parser.add_argument("--host", help="Sobrescribe server.host")
    parser.add_argument("--port", type=int, help="Sobrescribe server.port")
    parser.add_argument("--dev", action="store_true",
                        help="Modo desarrollo: servidor Flask con depurador y recarga automática")
    parser.add_argument("--no-reload", action="store_true",
                        help="Con --dev, desactiva la recarga (útil al depurar desde VS Code)")
    args = parser.parse_args()

    try:
        app = create_app(args.config)
    except ConfigError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2

    srv = app.config["SW"]["server"]
    host = args.host or srv["host"]
    port = args.port or srv["port"]

    if args.dev:
        cfg_file = Path(args.config) if args.config else default_config_path()
        templates = Path(app.template_folder)
        app.run(
            host=host,
            port=port,
            debug=True,
            use_reloader=not args.no_reload,
            reloader_type="stat",
            # Además del código Python, reinicia al cambiar la config o las plantillas
            extra_files=[str(cfg_file), *map(str, templates.rglob("*.html"))],
        )
        return 0

    from waitress import serve

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

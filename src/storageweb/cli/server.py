"""Comando ``serve``: el servidor web (Waitress, o el de desarrollo con ``--dev``)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .. import i18n
from ..i18n import _
from ..settings import ConfigError, default_config_path


def cmd_serve(args) -> int:
    from .. import create_app

    try:
        app = create_app(args.config)
    except ConfigError as exc:
        print(_("Configuration error: %(error)s", error=exc), file=sys.stderr)
        return 2
    srv = app.config["SW"]["server"]
    host = args.host or srv["host"]
    port = args.port or srv["port"]

    if args.dev:
        cfg_file = Path(args.config) if args.config else default_config_path()
        templates = Path(app.root_path) / app.template_folder
        catalogs = Path(i18n.LOCALE_DIR).rglob("*.po")
        app.run(host=host, port=port, debug=True, use_reloader=not args.no_reload, reloader_type="stat",
                # Además del código Python, reinicia al cambiar la config, las plantillas o las traducciones
                extra_files=[str(cfg_file), *map(str, templates.rglob("*.html")), *map(str, catalogs)])
        return 0

    from waitress import serve

    logging.getLogger("waitress").setLevel(logging.INFO)
    app.logger.info("StorageWeb listening on http://%s:%s (config: %s)", host, port,
                    app.config["SW"]["_config_path"])
    serve(app, host=host, port=port, threads=int(srv["threads"]),
          max_request_body_size=srv["max_upload_mb"] * 1024 * 1024 + 1024 * 1024,
          channel_timeout=300, ident="StorageWeb")
    return 0

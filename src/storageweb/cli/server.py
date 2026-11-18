"""Comando ``serve``: el servidor web (Waitress, o el de desarrollo con ``--dev``)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .. import i18n
from ..i18n import _, _l
from .common import command
from ..settings import ConfigError, default_config_path


def _serve_args(p):
    p.add_argument("--host", help=_("Overrides server.host"))
    p.add_argument("--port", type=int, help=_("Overrides server.port"))
    p.add_argument("--dev", action="store_true", help=_("Development: debugger and automatic reload"))
    p.add_argument("--no-reload", action="store_true", help=_("With --dev, without reload (for debugging)"))


def waitress_options(srv: dict) -> dict:
    """Opciones de Waitress para la sección ``server`` de la configuración.

    Detrás de un proxy, Waitress no debe borrar las cabeceras ``X-Forwarded-*`` (lo hace por defecto con las
    que no vienen de un ``trusted_proxy``): las valida ProxyFix con ``server.proxy_hops`` (``app.py``). Sin
    proxy se siguen borrando, y la aplicación tampoco las usaría.
    """
    return {"threads": int(srv["threads"]),
            "max_request_body_size": srv["max_upload_mb"] * 1024 * 1024 + 1024 * 1024,
            "channel_timeout": 300, "ident": "StorageWeb",
            "clear_untrusted_proxy_headers": not srv["behind_proxy"]}


def create_waitress(app, host: str | None = None, port: int | None = None):
    """El servidor Waitress de ``app`` sin arrancarlo (``.run()``): lo usa el servicio de Windows, que lo
    para desde otro hilo (``cli/service_host.py``)."""
    from waitress.server import create_server

    srv = app.config["SW"]["server"]
    return create_server(app, host=host or srv["host"], port=srv["port"] if port is None else port,
                         **waitress_options(srv))


@command("serve", _l("Start the web server"), _serve_args, needs_db=False, order=10)
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
    serve(app, host=host, port=port, **waitress_options(srv))
    return 0

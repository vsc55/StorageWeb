"""Capa web (Flask).

* ``views/``: páginas HTML (auth, files, admin/, groups, access, profile, settings/)
* ``api/``: API JSON (subidas por partes, /healthz)
* ``context``: conexión a BD, ajustes, avisos y diagnóstico de red por petición
* ``guards``: sesión, CSRF, control de acceso y cabeceras de seguridad
* ``nav``, ``search``: mapa de la administración y buscador
* ``templating``, ``errors``, ``background``: plantillas, páginas de error y mantenimiento periódico
* ``templates/`` y ``static/``: frontend
"""
from __future__ import annotations

from flask import Flask


def init_web(app: Flask) -> None:
    """Conecta la capa web a la aplicación: hooks de cada petición, plantillas, errores y blueprints."""
    from .background import apply_process_settings, maintenance_tick
    from .context import close_db
    from .errors import register_error_handlers
    from .guards import (check_csrf, ip_gate, load_current_user, maintenance_gate, reset_request_locale,
                         select_locale, set_security_headers)
    from .templating import init_templating
    from .views.metrics import count_request, start_timer

    # El orden importa: primero el usuario y su idioma, para que hasta el error de CSRF salga traducido
    app.before_request(start_timer)
    app.before_request(maintenance_gate)
    app.before_request(apply_process_settings)
    app.before_request(ip_gate)
    app.before_request(load_current_user)
    app.before_request(select_locale)
    app.before_request(check_csrf)
    app.before_request(maintenance_tick)
    app.after_request(set_security_headers)
    app.after_request(count_request)
    app.teardown_request(reset_request_locale)
    app.teardown_appcontext(close_db)
    init_templating(app)
    register_error_handlers(app)
    register_blueprints(app)


def register_blueprints(app: Flask) -> None:
    from .api import health, uploads
    from .views import (access, admin, auth, brand, connect, dav, files, groups, links, locations, metrics, mfa,
                        profile, roles, settings)

    for module in (auth, mfa, files, admin, groups, access, locations, settings, brand, profile, connect, uploads,
                   health, dav, metrics, links, roles):
        app.register_blueprint(module.bp)

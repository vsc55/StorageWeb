"""Plantillas: i18n de Jinja, filtros y las variables comunes a todas las páginas."""
from __future__ import annotations

from flask import Flask, g

from .. import __version__, audit_levels, i18n
from ..i18n import _l
from ..core import branding, diagnostics, tokens
from ..core.permissions import ROLE_LABELS, is_admin
from .. import providers
from ..providers import local
from ..settings import env_name, location_types
from . import js_messages, nav
from .context import admin_alerts, boot_config, get_db, runtime, settings
from .guards import csrf_token
from .views.profile import THEME_ICONS, THEME_LABELS, THEMES, current_theme



LEVEL_LABELS = {"debug": _l("Debug"), "info": _l("Information"), "warning": _l("Warning"), "error": _l("Error"),
                "critical": _l("Critical")}

def ua_summary(user_agent: str | None) -> str:
    """«Chrome · Windows» a partir del User-Agent (para la lista de sesiones)."""
    ua = user_agent or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("Chrome/", "Chrome"), ("Safari/", "Safari"), ("curl/", "curl"),
                                           ("python", "Python")) if key in ua), "")
    system = next((name for key, name in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iOS"),
                                          ("iPad", "iOS"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if key in ua), "")
    return " · ".join(x for x in (browser, system) if x) or (ua[:40] or "—")


def _admin_nav(user) -> dict:
    """Zonas de la administración, página actual y avisos (solo para administradores)."""
    if not is_admin(user):
        return {"nav_zones": (), "nav_zone": None, "nav_page": None, "admin_alert_count": 0, "banner_alert": None}
    found = [a for a in admin_alerts() if a["level"] != "info"]
    return {**nav.context(runtime().modified_paths(get_db()), runtime().locked()), "admin_alert_count": len(found),
            "nav_alert_pages": {a["page"] for a in found},
            # El secreto de Entra ID se avisa en todas las páginas (en el Resumen ya sale en la lista)
            "banner_alert": next((a for a in found if a["key"].startswith("secret_")), None)}


def _brand() -> dict:
    cfg = settings()
    color = cfg["branding"]["primary_color"]
    found = {kind: branding.image_path(cfg, kind) for kind in branding.IMAGES}
    # La versión va en las URL (se cachean una hora): cambia con el color y con cada imagen subida
    version = color + "".join(f"{p.name}{int(p.stat().st_mtime)}" for p in found.values() if p)
    return {"color": color, "logo": bool(found["logo"]), "login_image": bool(found["login_image"]),
            "login_art": branding.pick_login_art(cfg["branding"]["login_art"]),
            "version": version or "0"}


def init_templating(app: Flask) -> None:
    # i18n: {{ _("Text") }}, {{ _("Hi %(name)s", name=x) }}, {{ ngettext(...) }}
    app.jinja_env.add_extension("jinja2.ext.i18n")
    app.jinja_env.install_gettext_callables(i18n.raw_gettext, i18n.raw_ngettext, newstyle=True)
    app.jinja_env.filters["datetime"] = i18n.format_datetime
    app.jinja_env.filters["filesize"] = i18n.format_size
    app.jinja_env.filters["duration"] = i18n.format_duration
    app.jinja_env.filters["ua_summary"] = ua_summary
    app.jinja_env.globals["env_name"] = env_name
    # Niveles de la auditoría (audit_levels): la lista y su nombre en el idioma de la página
    app.jinja_env.globals["audit_levels"] = audit_levels.LEVELS
    app.jinja_env.globals["level_label"] = lambda level: str(LEVEL_LABELS.get(level, level))
    app.jinja_env.globals["location_type"] = location_types.get  # esquema de un tipo de ubicación (S3, SMB…)
    app.jinja_env.globals["auth_method"] = providers.get  # método de inicio de sesión de un origen (local, entra…)
    # Cuándo deja de valer un token: su fecha o, con la política security.api_token_max_days, antes
    app.jinja_env.globals["token_expiry"] = lambda t: tokens.effective_expiry(
        t, settings()["security"]["api_token_max_days"])
    # Dónde empieza el selector de rutas (admin/path-picker.js) en el disco del servidor, y dónde viven las carpetas
    # personales: {"home": base de las carpetas personales, "home_location": su ubicación o "", "data": data_dir}
    app.jinja_env.globals["pick_start"] = lambda: {
        "home": diagnostics.home_base(settings()["storage"]["home_template"]),
        "home_location": settings()["storage"].get("home_location", ""),
        "data": boot_config()["data_dir"]}
    # La longitud mínima de una contraseña nueva (security.password_min_length), para el minlength de los formularios
    app.jinja_env.globals["password_min_length"] = lambda: settings()["security"]["password_min_length"]
    # Lo que se pide a una contraseña nueva, en una frase (el title de esos campos): «Al menos 12 caracteres, con…»
    app.jinja_env.globals["password_rules_text"] = lambda: local.describe(local.rules(settings()))

    @app.context_processor
    def inject_globals():
        user = g.get("user")
        return {"csrf_token": csrf_token, "app_name": settings()["app_name"], "current_user": user,
                "is_admin": is_admin(user), "ROLE_LABELS": ROLE_LABELS, "app_version": __version__,
                "current_locale": i18n.get_locale(),
                "available_locales": [(code, i18n.locale_display_name(code)) for code in i18n.LOCALES],
                "current_theme": current_theme(),
                "available_themes": [(code, THEME_LABELS[code], THEME_ICONS[code]) for code in THEMES],
                "js_messages": js_messages.catalog,
                "brand": _brand(), **_admin_nav(user)}

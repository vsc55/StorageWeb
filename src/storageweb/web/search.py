"""Buscador de la administración (Ctrl+K y ``/admin/search``).

Busca en páginas (``nav.ZONES``), ajustes (lleva al campo exacto: ``#f-<ruta-con-guiones>``, el
ancla que deja la macro ``origin``), acciones frecuentes, usuarios, grupos y carpetas compartidas.
No distingue mayúsculas ni tildes y exige que aparezcan todas las palabras.
"""
from __future__ import annotations

import unicodedata
from sqlite3 import Connection

from flask import url_for

from ..core import groups as group_core
from ..core.permissions import PERMISSION_LABELS
from ..db.repositories import groups as group_repo
from ..db.repositories import users
from ..i18n import _, _l
from ..settings import PERMISSIONS
from . import nav

MAX_RESULTS = 30
MAX_PER_ENTITY = 6

GROUP_LABELS = {"action": _l("Actions"), "page": _l("Pages"), "setting": _l("Settings"), "user": _l("Users"),
                "group": _l("Groups"), "share": _l("Shared folders")}

# (ruta en la configuración, etiqueta del formulario, sinónimos). La página sale de nav.page_for_path.
SETTINGS = (
    ("app_name", _l("Application name"), "nombre aplicación título name title"),
    ("default_locale", _l("Default language"), "idioma español inglés language locale"),
    ("branding.primary_color", _l("Use my own main color"), "color marca branding"),
    ("branding.logo", _l("Logo"), "logo imagen marca branding image"),
    ("network.public_url", _l("Name users type in the browser"), "fqdn dominio url pública https proxy public domain"),
    ("storage.home_template", _l("Personal folder template"), "home carpeta personal plantilla"),
    ("storage.create_home", _l("Create the personal folder on first access"), "home crear"),
    ("storage.create_shares", _l("Create shared folders if they do not exist"), "compartidas crear shares"),
    ("storage.show_hidden", _l("Show hidden files"), "ocultos punto hidden dotfiles"),
    ("storage.max_file_size_mb", _l("Maximum size per file (MB)"), "tamaño límite subida upload size limit"),
    ("auth.local.enabled", _l("Local users"), "local contraseña password login"),
    ("auth.pam.enabled", "PAM", "pam linux sistema system"),
    ("auth.pam.allowed_groups", _l("Allowed groups"), "pam grupos permitidos"),
    ("auth.pam.admin_groups", _l("Groups with the administrator role"), "pam administradores admins"),
    ("auth.entra.enabled", "Microsoft Entra ID", "entra azure microsoft sso oidc oauth"),
    ("auth.entra.tenant_id", "Tenant ID", "entra tenant inquilino"),
    ("auth.entra.client_id", "Client ID", "entra aplicación app client"),
    ("auth.entra.client_secret", "Client secret", "entra secreto secret contraseña"),
    ("auth.entra.secret_expires", _l("The secret expires on"), "entra secreto caducidad caduca expira expiry"),
    ("auth.entra.redirect_uri", "Redirect URI", "entra redirección callback"),
    ("auth.entra.button_label", _l("Button text"), "entra botón button"),
    ("auth.entra.auto_provision", _l("Create the user automatically on first sign-in"),
     "entra alta automática provisioning"),
    ("auth.entra.default_role", _l("Default role"), "entra rol role"),
    ("auth.entra.allowed_groups", _l("Allowed groups / App Roles"), "entra grupos permitidos app roles"),
    ("auth.entra.role_mappings", _l("Group / App Role → role mapping"), "entra rol mapeo administradores mapping"),
    ("auth.entra.single_logout", _l("Also sign out of Microsoft when signing out"), "entra cerrar sesión logout"),
    ("auth.entra.username_claim", _l("User name claim"), "entra claim usuario"),
    ("security.max_login_failures", _l("Failed attempts before locking"), "intentos fallidos contraseña bloqueo"),
    ("security.lockout_minutes", _l("Lockout minutes"), "bloqueo minutos lockout"),
    ("security.ipban_enabled", _l("Block addresses with many offenses"), "ip bloqueo automático ban infracciones"),
    ("security.ipban_threshold", _l("Offenses"), "ip bloqueo infracciones umbral"),
    ("security.ipban_minutes", _l("Block for (minutes)"), "ip bloqueo duración"),
    ("security.api_tokens", _l("Allow personal API tokens"), "api tokens scripts"),
    ("maintenance.audit_retention_days", _l("Keep the audit log (days)"), "auditoría retención días borrar"),
    ("maintenance.backup_interval_hours", _l("Automatic backup every (hours)"),
     "copia seguridad backup automática horas"),
    ("maintenance.backup_keep", _l("Backups to keep"), "copias conservar backup retención"),
) + tuple((f"permissions.user.{p}", None, "permiso rol usuario permission role") for p in PERMISSIONS)

# (icono, título, endpoint, argumentos, ancla, sinónimos)
ACTIONS = (
    ("user", _l("New user"), "admin.user_new", {}, "", "alta crear usuario cuenta add create"),
    ("users", _l("New group"), "groups.new", {}, "", "crear grupo add create"),
    ("folder", _l("New shared folder"), "access.folder_new", {}, "", "crear carpeta compartida share add create"),
    ("download", _l("Create a backup now"), "settings.section", {"name": "backups"}, "backups",
     "copia seguridad backup ahora"),
    ("lock", _l("Block an IP address"), "settings.section", {"name": "ips"}, "ip-rules", "ip bloquear ban"),
    ("key", _l("Renew the Entra ID secret"), "settings.section", {"name": "auth"}, "f-auth-entra-secret_expires",
     "secreto entra renovar rotar microsoft secret rotate"),
    ("globe", _l("Register the application in Entra ID"), "settings.entra_register_page", {}, "",
     "entra registrar app microsoft"),
    ("logout", _l("Close all sessions"), "settings.section", {"name": "sessions"}, "", "sesiones cerrar todas logout"),
    ("audit", _l("Export the audit log (CSV)"), "admin.audit_export", {}, "", "auditoría exportar csv"),
    ("sync", _l("Compact the database"), "settings.section", {"name": "backups"}, "", "base datos compactar vacuum"),
)


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _matches(terms: list[str], *fields) -> bool:
    haystack = _norm(" ".join(str(f) for f in fields if f))
    return all(term in haystack for term in terms)


def _where(page_key: str) -> str:
    return f"{nav.ZONE_OF[page_key].label} → {nav.PAGES[page_key].label}"


def _value(cfg: dict, path: str) -> str:
    """Valor actual para mostrarlo al lado del ajuste (nunca los secretos)."""
    if path.endswith(("client_secret", "logo")):
        return ""
    value = cfg
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return ""
        value = value[part]
    if isinstance(value, bool):
        return _("yes") if value else _("no")
    if isinstance(value, (list, dict)):
        return str(len(value)) if value else ""
    return str(value)[:40]


def _item(kind: str, title, where: str, url: str, hint: str = "", icon: str = "") -> dict:
    return {"kind": kind, "group": str(GROUP_LABELS[kind]), "title": str(title), "path": where, "url": url,
            "hint": hint, "icon": icon}


def find(query: str, conn: Connection, cfg: dict) -> list[dict]:
    terms = _norm(query).split()
    results: list[dict] = []

    for icon, title, endpoint, args, anchor, words in ACTIONS:
        if not terms or _matches(terms, title, words):
            url = url_for(endpoint, **args) + (f"#{anchor}" if anchor else "")
            results.append(_item("action", title, "", url, icon=icon))

    for zone in nav.ZONES:
        for page in zone.pages:
            if not terms or _matches(terms, page.label, zone.label, page.hint, page.words):
                results.append(_item("page", page.label, str(zone.label), page.url(), str(page.hint), zone.icon))

    if terms:
        for path, label, words in SETTINGS:
            label = label or PERMISSION_LABELS[path.rsplit(".", 1)[1]]
            page = nav.page_for_path(path)
            if _matches(terms, label, words, path, nav.PAGES[page].label):
                results.append(_item("setting", label, _where(page),
                                     nav.PAGES[page].url() + "#f-" + path.replace(".", "-"), _value(cfg, path)))

        # Se filtra aquí y no en SQL para no distinguir tildes (LIKE sí las distingue)
        found = [u for u in users.list_all(conn) if _matches(terms, u["username"], u["display_name"], u["email"])]
        for row in found[:MAX_PER_ENTITY]:
            results.append(_item("user", row["display_name"] or row["username"],
                                 f"{row['username']} · {row['source']}", url_for("admin.user_edit", user_id=row["id"]),
                                 "" if row["enabled"] else _("Disabled"), "user"))
        found = [grp for grp in group_repo.list_all(conn)
                 if _matches(terms, grp["name"], group_core.label(grp), grp["description"], grp["external_id"])]
        for row in found[:MAX_PER_ENTITY]:
            results.append(_item("group", group_core.label(row), row["name"],
                                 url_for("groups.edit", group_id=row["id"]), icon="users"))
        for share in cfg["storage"]["shares"]:
            if _matches(terms, share["label"], share["name"], share["path"]):
                results.append(_item("share", share["label"], f"/f/{share['name']}",
                                     url_for("access.folder", name=share["name"]), icon="folder"))
    return results[:MAX_RESULTS]

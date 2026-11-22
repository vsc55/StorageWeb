"""Perfil del usuario: datos personales, idioma, tema, contraseña, sesiones y tokens de API."""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from ...core import links, mfa, quota, storage, tokens
from ...core.permissions import permissions_for
from ...core.accounts import source_labels, stores_password
from ...db.repositories import api_tokens, audit, users
from ...db.repositories import sessions as session_repo
from ...i18n import LOCALES, _, _l, locale_display_name, ngettext
from ...i18n import normalize as normalize_locale
from ...providers import local
from ..context import external_url, get_db, runtime, settings
from ..guards import audit_event, client_ip, login_required, require_api_tokens, safe_next
from . import mfa as mfa_views
from .links import listing_context as link_listing

bp = Blueprint("profile", __name__)

THEMES = ("system", "light", "dark")
THEME_LABELS = {"system": _l("System"), "light": _l("Light"), "dark": _l("Dark")}
THEME_ICONS = {"system": "monitor", "light": "sun", "dark": "moon"}


def normalize_theme(value: str | None) -> str | None:
    return value if value in THEMES else None


def current_theme() -> str:
    """Tema de la petición: el del usuario, el elegido en la sesión o el del sistema."""
    user = g.get("user")
    return (normalize_theme(user["theme"]) if user is not None else None) \
        or normalize_theme(session.get("theme")) or "system"


def _audit(action: str, detail: str | None = None) -> None:
    audit.log(get_db(), action, g.user["username"], username=g.user["username"], ip=client_ip(), detail=detail)


@bp.route("/theme", methods=["POST"])
def change_theme():
    """Cambio rápido de tema desde el menú (también antes de iniciar sesión)."""
    theme = normalize_theme(request.form.get("theme"))
    if theme:
        session["theme"] = theme
        if g.get("user") is not None:
            users.update(get_db(), g.user["id"], theme=theme)
        audit_event("preference_changed", None, f"theme={theme}")
    return redirect(safe_next(request.form.get("next")))


# Secciones de «Mi perfil» (submenú lateral, como las zonas de la administración): clave, título y descripción
SECTIONS = (
    ("account", _l("Account"), _l("Your name, your email and how the application looks.")),
    ("security", _l("Security"), _l("How you sign in and where you have a session open.")),
    ("tokens", _l("API tokens"), _l("To use your files from scripts and programs without your password.")),
    ("drive", _l("Network drive"),
     _l("Your folders as a drive in the file explorer (Windows, macOS, Linux) or with rclone, Cyberduck or WinSCP.")),
    ("space", _l("Space"), _l("What your personal folder takes up.")),
    ("links", _l("Share links"), _l("What you have shared with people outside: copy a link again or stop sharing.")),
)


def _visible_sections(cfg, home_quota, home_space) -> list[str]:
    sec = cfg["security"]
    shown = {"account", "security"}
    if sec["api_tokens"]:
        shown.add("tokens")
    if sec["webdav"] and (sec["api_tokens"] or sec["webdav_passwords"]):
        shown.add("drive")
    if home_quota or home_space:
        shown.add("space")
    if links.enabled(cfg) and ("share" in permissions_for(g.user, cfg) or links.for_user(get_db(), g.user)):
        shown.add("links")
    return [key for key, _label, _desc in SECTIONS if key in shown]


def section_url(section: str) -> str:
    return url_for("profile.profile") if section == "account" else url_for("profile.section", section=section)


def _render(section: str):
    user, cfg = g.user, settings()
    home = storage.available_roots(user, cfg)[0]
    home_quota, home_space = quota.status(home), storage.space_of(home)
    visible = _visible_sections(cfg, home_quota, home_space)
    if section not in visible:
        abort(404)
    labels = {key: (label, desc) for key, label, desc in SECTIONS}
    context = dict(
        user=user, section=section, section_label=labels[section][0], section_description=labels[section][1],
        sections=[(key, labels[key][0], section_url(key)) for key in visible],
        editable=stores_password(user["source"]), own_password=stores_password(user["source"]),
        SOURCE_LABELS=source_labels(), tokens_enabled=cfg["security"]["api_tokens"],
        webdav="drive" in visible, webdav_passwords=cfg["security"]["webdav_passwords"])
    if section == "account":
        context.update(locales=[(code, locale_display_name(code)) for code in LOCALES],
                       themes=[(code, THEME_LABELS[code]) for code in THEMES],
                       user_locale=normalize_locale(user["locale"]) or "",
                       user_theme=normalize_theme(user["theme"]) or "system")
    elif section == "security":
        context.update(my_sessions=session_repo.list_all(get_db(), user["id"]), current_sid=g.get("session_id"),
                       mfa_applies=mfa.applies(user), mfa=mfa.status(get_db(), user),
                       mfa_required=mfa.required(cfg, user), passkeys_on=mfa_views.passkeys_available(),
                       passwordless=mfa.passwordless_on(cfg) and mfa.passwordless_allowed(cfg, user),
                       mfa_unlocked=mfa_views.proof_ok(user), mfa_proof_minutes=mfa_views.PROOF_SECONDS // 60)
    elif section == "tokens":
        context.update(my_tokens=api_tokens.list_for_user(get_db(), user["id"]),
                       new_token=session.pop("new_token", None),
                       SCOPE_LABELS=tokens.SCOPE_LABELS,
                       EXPIRY_DAYS=tokens.allowed_days(cfg["security"]["api_token_max_days"]),
                       token_max_days=cfg["security"]["api_token_max_days"])
    elif section == "drive":
        context.update(webdav_url=external_url("dav.root"), mfa_blocks_password=bool(mfa.needed(get_db(), cfg, user)))
    elif section == "space":
        context.update(home_quota=home_quota, home_space=home_space)
    elif section == "links":
        key = runtime().secrets_key
        labels = {r["name"]: str(r["label"]) for r in storage.available_roots(user, cfg)}
        rows = [{**dict(row), "state": links.state(row), "folder": labels.get(row["root"], row["root"]),
                 "url": (lambda t: external_url("links.public", token=t) if t else "")(links.token_of(row, key))}
                for row in links.for_user(get_db(), user)]
        # Filtro: activos de entrada; «borrados» son los que ya no existen y solo conservan su historial
        shown, extra = link_listing(rows, "links_show", user["username"])
        context.update(my_links=shown, **extra)
    return render_template("profile.html", **context)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Sección «Cuenta»: nombre, email, idioma y tema."""
    user = g.user
    if request.method == "POST":
        fields = {}
        raw_locale = request.form.get("locale")
        locale = normalize_locale(raw_locale)
        theme = normalize_theme(request.form.get("theme"))
        if locale:
            fields["locale"] = locale
            session["locale"] = locale
        elif raw_locale == "":  # «Idioma del navegador»: se olvida la preferencia
            fields["locale"] = None
            session.pop("locale", None)
        if theme:
            fields["theme"] = theme
            session["theme"] = theme
        if stores_password(user["source"]):  # en Entra/PAM los datos personales vienen del origen
            fields["display_name"] = request.form.get("display_name", "").strip()[:200] or None
            fields["email"] = request.form.get("email", "").strip()[:200] or None
        users.update(get_db(), user["id"], **fields)
        _audit("profile_updated", ", ".join(sorted(fields)))
        flash(_("Profile saved."), "info")
        return redirect(url_for("profile.profile"))
    return _render("account")


@bp.route("/profile/<any(security, tokens, drive, space, links):section>")
@login_required
def section(section: str):
    return _render(section)


@bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    user = g.user
    if not stores_password(user["source"]):
        abort(403, description=_("Only local users have a password that can be changed."))
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    if not local.verify(user["password_hash"], current):
        _audit("password_change_failed")
        flash(_("The current password is not correct."), "error")
    elif new != request.form.get("repeat_password", ""):
        flash(_("The new passwords do not match."), "error")
    elif new == current:
        flash(_("The new password must be different from the current one."), "error")
    else:
        try:
            users.update(get_db(), user["id"], password_hash=local.hash_password(
                new, username=user["username"], **local.rules(settings())))
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            closed = session_repo.delete_for_user(get_db(), user["id"], keep=g.get("session_id"))
            _audit("password_changed", f"sessions_closed={closed}")
            flash(_("Password changed. Your other sessions have been closed."), "info")
    return redirect(section_url("security") + "#password")


# --------------------------------------------------------------------------- sesiones

@bp.route("/profile/sessions/<sid>/close", methods=["POST"])
@login_required
def session_close(sid: str):
    row = session_repo.get(get_db(), sid)
    if row is not None and row["user_id"] == g.user["id"] and sid != g.get("session_id"):
        session_repo.delete(get_db(), sid)
        _audit("session_closed", row["ip"])
        flash(_("Session closed."), "info")
    return redirect(section_url("security") + "#sessions")


@bp.route("/profile/sessions/close-others", methods=["POST"])
@login_required
def sessions_close_others():
    closed = session_repo.delete_for_user(get_db(), g.user["id"], keep=g.get("session_id"))
    _audit("sessions_closed", str(closed))
    flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    return redirect(section_url("security") + "#sessions")


# --------------------------------------------------------------------------- tokens de API

@bp.route("/profile/tokens", methods=["POST"])
@login_required
def token_create():
    require_api_tokens()
    try:
        plain, _token_id = tokens.create(get_db(), g.user, name=request.form.get("name", ""),
                                         scope=request.form.get("scope", "read"),
                                         days=request.form.get("days", 90, type=int),
                                         max_days=settings()["security"]["api_token_max_days"])
    except tokens.TokenError as exc:
        flash(str(exc), "error")
    else:
        session["new_token"] = plain  # se muestra una sola vez
        _audit("api_token_created", request.form.get("name", "").strip())
    return redirect(section_url("tokens"))


@bp.route("/profile/tokens/<int:token_id>/rotate", methods=["POST"])
@login_required
def token_rotate(token_id: int):
    """Rotar: un secreto nuevo para el mismo token (nombre, alcance y caducidad); el anterior deja de valer."""
    require_api_tokens()
    try:
        plain, _token_id = tokens.rotate(get_db(), g.user, api_tokens.get(get_db(), token_id),
                                         settings()["security"]["api_token_max_days"])
    except tokens.TokenError:
        abort(404)
    session["new_token"] = plain  # se muestra una sola vez
    token = api_tokens.get(get_db(), _token_id)
    _audit("api_token_rotated", token["name"])
    flash(_("Token «%(name)s» rotated: copy the new one; the previous one no longer works.", name=token["name"]), "info")
    return redirect(section_url("tokens"))


@bp.route("/profile/tokens/<int:token_id>/delete", methods=["POST"])
@login_required
def token_delete(token_id: int):
    token = api_tokens.get(get_db(), token_id)
    if token is None or token["user_id"] != g.user["id"]:
        abort(404)
    api_tokens.delete(get_db(), token_id)
    _audit("api_token_revoked", token["name"])
    flash(_("Token «%(name)s» revoked.", name=token["name"]), "info")
    return redirect(section_url("tokens"))

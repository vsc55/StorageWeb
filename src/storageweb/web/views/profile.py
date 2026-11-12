"""Perfil del usuario: datos personales, idioma, tema y cambio de contraseña."""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from ...core.accounts import SOURCE_LABELS
from ...db.repositories import audit, users
from ...i18n import LOCALES, _, _l, locale_display_name
from ...i18n import normalize as normalize_locale
from ...providers import local
from ..context import get_db
from ..guards import client_ip, login_required, safe_next

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
    return redirect(safe_next(request.form.get("next")))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = g.user
    editable = user["source"] == "local"  # en Entra/PAM los datos personales vienen del origen
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
        if editable:
            fields["display_name"] = request.form.get("display_name", "").strip()[:200] or None
            fields["email"] = request.form.get("email", "").strip()[:200] or None
        users.update(get_db(), user["id"], **fields)
        _audit("profile_updated", ", ".join(sorted(fields)))
        flash(_("Profile saved."), "info")
        return redirect(url_for("profile.profile"))

    return render_template(
        "profile.html", user=user, editable=editable, SOURCE_LABELS=SOURCE_LABELS,
        locales=[(code, locale_display_name(code)) for code in LOCALES],
        themes=[(code, THEME_LABELS[code]) for code in THEMES],
        user_locale=normalize_locale(user["locale"]) or "",
        user_theme=normalize_theme(user["theme"]) or "system")


@bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    user = g.user
    if user["source"] != "local":
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
            users.update(get_db(), user["id"], password_hash=local.hash_password(new))
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            _audit("password_changed")
            flash(_("Password changed."), "info")
    return redirect(url_for("profile.profile") + "#password")

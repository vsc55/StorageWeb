"""Rutas de inicio/cierre de sesión: formulario (local/PAM) y SSO (Entra ID)."""
from __future__ import annotations

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ...core import accounts, ipban
from ...db.repositories import audit, users
from ...i18n import _
from ...i18n import normalize as normalize_locale
from ...providers import SSOError, get_sso_provider
from ..context import external_url, get_db, settings, throttle
from ..guards import client_ip, end_session, safe_next, start_session

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    cfg = settings()
    if g.get("user"):
        return redirect(safe_next(request.args.get("next")))
    auth = cfg["auth"]
    form_enabled = auth["local"]["enabled"] or auth["pam"]["enabled"]
    next_url = request.values.get("next", "")

    if request.method == "POST" and form_enabled:
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = client_ip()
        limiter = throttle()
        limiter.configure(cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60)

        if not username or not password:
            flash(_("Enter your user name and password."), "error")
        elif limiter.is_blocked(ip, username):
            audit.log(get_db(), "login_blocked", username=username, ip=ip)
            flash(_("Too many failed attempts. Wait a few minutes."), "error")
        else:
            user = accounts.authenticate_password(get_db(), cfg, username, password)
            if user:
                limiter.success(ip, username)
                start_session(user)
                audit.log(get_db(), "login", username=user["username"], ip=ip, detail=user["source"])
                return redirect(safe_next(next_url))
            limiter.failure(ip, username)
            audit.log(get_db(), "login_failed", username=username, ip=ip)
            ipban.offense(get_db(), cfg, ip, "login_failed")
            flash(_("Wrong user name or password."), "error")

    return render_template("login.html", form_enabled=form_enabled,
                           entra_enabled=auth["entra"]["enabled"],
                           entra_label=auth["entra"]["button_label"] or _("Sign in with Microsoft"),
                           next_url=next_url)


@bp.route("/locale", methods=["POST"])
def change_locale():
    """Cambia el idioma: se guarda en la sesión y, si hay usuario, en su cuenta."""
    locale = normalize_locale(request.form.get("locale"))
    if locale:
        session["locale"] = locale
        if g.get("user") is not None:
            users.update(get_db(), g.user["id"], locale=locale)
    return redirect(safe_next(request.form.get("next")))


@bp.route("/logout", methods=["POST"])
def logout():
    user = g.get("user")
    src = session.get("src")
    if user:
        audit.log(get_db(), "logout", username=user["username"], ip=client_ip())
    end_session()
    ecfg = settings()["auth"]["entra"]
    if src == "entra" and ecfg["enabled"] and ecfg["single_logout"]:
        provider = get_sso_provider(ecfg)
        return redirect(provider.logout_url(external_url("auth.login")))
    flash(_("You have signed out."), "info")
    return redirect(url_for("auth.login"))


def _redirect_uri(ecfg: dict) -> str:
    return ecfg["redirect_uri"] or external_url("auth.entra_callback")


@bp.route("/auth/entra/login")
def entra_login():
    ecfg = settings()["auth"]["entra"]
    if not ecfg["enabled"]:
        return redirect(url_for("auth.login"))
    try:
        auth_url, flow = get_sso_provider(ecfg).begin(_redirect_uri(ecfg))
    except Exception:  # p. ej. MSAL sin conexión al descubrir la autoridad
        current_app.logger.exception("Could not start the SSO login")
        flash(_("Could not contact the identity provider."), "error")
        return redirect(url_for("auth.login"))
    session["entra_flow"] = flow
    session["entra_next"] = request.args.get("next", "")
    return redirect(auth_url)


@bp.route("/auth/entra/callback")
def entra_callback():
    ecfg = settings()["auth"]["entra"]
    if not ecfg["enabled"]:
        return redirect(url_for("auth.login"))
    ip = client_ip()
    flow = session.pop("entra_flow", None)
    next_url = session.pop("entra_next", "")
    if not flow:
        flash(_("The sign-in session expired. Try again."), "error")
        return redirect(url_for("auth.login"))
    try:
        claims = get_sso_provider(ecfg, flow.get("provider")).complete(flow, request.args.to_dict())
        user = accounts.login_with_claims(get_db(), ecfg, claims, ip=ip)
    except SSOError as exc:
        current_app.logger.warning("SSO error: %s", exc)
        audit.log(get_db(), "login_failed", ip=ip, detail=f"entra:{exc.code}")
        flash(_("Could not sign in with Microsoft."), "error")
        return redirect(url_for("auth.login"))
    except accounts.AccountError as exc:
        audit.log(get_db(), "login_denied", ip=ip, detail=f"entra:{exc.code}")
        flash(exc.message, "error")
        return redirect(url_for("auth.login"))

    start_session(user)
    audit.log(get_db(), "login", username=user["username"], ip=ip, detail="entra")
    return redirect(safe_next(next_url))

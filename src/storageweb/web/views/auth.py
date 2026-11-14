"""Rutas de inicio/cierre de sesión: el formulario (métodos con contraseña) y el SSO de cada método.

Nada aquí depende de un proveedor concreto: ``/auth/<método>/login`` y ``/auth/<método>/callback``
sirven para cualquier método SSO registrado (``providers.AuthMethod``). Para Entra ID la dirección
de vuelta es ``/auth/entra/callback``.
"""
from __future__ import annotations

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ... import providers
from ...core import accounts, ipban
from ...db.repositories import audit, users
from ...i18n import _
from ...i18n import normalize as normalize_locale
from ...providers import SSOError
from ..context import external_url, get_db, settings, throttle
from ..guards import client_ip, end_session, safe_next, start_session

bp = Blueprint("auth", __name__)


def _enabled(cfg: dict, *, sso: bool) -> list:
    return [m for m in providers.methods() if m.enabled(cfg) and (m.sso if sso else m.password)]


@bp.route("/login", methods=["GET", "POST"])
def login():
    cfg = settings()
    if g.get("user"):
        return redirect(safe_next(request.args.get("next")))
    form_enabled = bool(_enabled(cfg, sso=False))
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

    buttons = [(m.key, m.login_button(m.section(cfg))) for m in _enabled(cfg, sso=True)]
    return render_template("login.html", form_enabled=form_enabled, sso_buttons=buttons, next_url=next_url)


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
    method = providers.get(session.get("src") or "")
    if user:
        audit.log(get_db(), "logout", username=user["username"], ip=client_ip())
    end_session()
    cfg = settings()
    if method is not None and method.sso and method.enabled(cfg):
        url = method.logout_url(method.section(cfg), external_url("auth.login"))
        if url:  # cerrar también la sesión en el proveedor
            return redirect(url)
    flash(_("You have signed out."), "info")
    return redirect(url_for("auth.login"))


def redirect_uri(key: str, section: dict) -> str:
    """Dirección de vuelta del método: la configurada o ``/auth/<método>/callback`` en la dirección pública."""
    method = providers.get(key)
    return (method.redirect_uri(section) if method else "") or external_url("auth.sso_callback", method=key)


def _sso_method(key: str):
    method = providers.get(key)
    if method is None or not method.sso:
        abort(404)
    return method


@bp.route("/auth/<method>/login")
def sso_login(method: str):
    m = _sso_method(method)
    cfg = settings()
    if not m.enabled(cfg):
        return redirect(url_for("auth.login"))
    section = m.section(cfg)
    try:
        auth_url, flow = m.begin(section, redirect_uri(m.key, section))
    except Exception:  # p. ej. MSAL sin conexión al descubrir la autoridad
        current_app.logger.exception("Could not start the SSO login")
        flash(_("Could not contact the identity provider."), "error")
        return redirect(url_for("auth.login"))
    session["sso"] = {"method": m.key, "flow": flow, "next": request.args.get("next", "")}
    return redirect(auth_url)


@bp.route("/auth/<method>/callback")
def sso_callback(method: str):
    m = _sso_method(method)
    cfg = settings()
    if not m.enabled(cfg):
        return redirect(url_for("auth.login"))
    ip = client_ip()
    pending = session.pop("sso", None) or {}
    if not pending.get("flow") or pending.get("method") != m.key:
        flash(_("The sign-in session expired. Try again."), "error")
        return redirect(url_for("auth.login"))
    try:
        user = accounts.complete_sso(get_db(), cfg, m.key, pending["flow"], request.args.to_dict(), ip=ip)
    except SSOError as exc:
        current_app.logger.warning("SSO error: %s", exc)
        audit.log(get_db(), "login_failed", ip=ip, detail=f"{m.key}:{exc.code}")
        flash(_("Could not sign in with %(method)s.", method=m.label), "error")
        return redirect(url_for("auth.login"))
    except accounts.AccountError as exc:
        audit.log(get_db(), "login_denied", ip=ip, detail=f"{m.key}:{exc.code}")
        flash(exc.message, "error")
        return redirect(url_for("auth.login"))

    start_session(user)
    audit.log(get_db(), "login", username=user["username"], ip=ip, detail=m.key)
    return redirect(safe_next(pending.get("next", "")))

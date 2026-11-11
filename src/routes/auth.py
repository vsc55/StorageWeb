"""Rutas de inicio/cierre de sesión: formulario (local/PAM) y SSO (Entra ID)."""
from __future__ import annotations

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ..config import settings
from ..core import accounts
from ..db import audit
from ..providers import SSOError, get_sso_provider
from .guards import client_ip, safe_next, start_session

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    cfg = settings.current()
    if g.get("user"):
        return redirect(safe_next(request.args.get("next")))
    auth = cfg["auth"]
    form_enabled = auth["local"]["enabled"] or auth["pam"]["enabled"]
    next_url = request.values.get("next", "")

    if request.method == "POST" and form_enabled:
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = client_ip()
        throttle = current_app.extensions["sw_throttle"]
        throttle.configure(cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60)

        if not username or not password:
            flash("Introduce usuario y contraseña.", "error")
        elif throttle.is_blocked(ip, username):
            audit.log("login_blocked", username=username, ip=ip)
            flash("Demasiados intentos fallidos. Espera unos minutos.", "error")
        else:
            user = accounts.authenticate_password(cfg, username, password)
            if user:
                throttle.success(ip, username)
                start_session(user)
                audit.log("login", username=user["username"], ip=ip, detail=user["source"])
                return redirect(safe_next(next_url))
            throttle.failure(ip, username)
            audit.log("login_failed", username=username, ip=ip)
            flash("Usuario o contraseña incorrectos.", "error")

    return render_template("login.html", form_enabled=form_enabled,
                           entra_enabled=auth["entra"]["enabled"],
                           entra_label=auth["entra"]["button_label"], next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    user = g.get("user")
    src = session.get("src")
    if user:
        audit.log("logout", username=user["username"], ip=client_ip())
    session.clear()
    ecfg = settings.current()["auth"]["entra"]
    if src == "entra" and ecfg["enabled"] and ecfg["single_logout"]:
        provider = get_sso_provider(ecfg)
        return redirect(provider.logout_url(url_for("auth.login", _external=True)))
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))


def _redirect_uri(ecfg: dict) -> str:
    return ecfg["redirect_uri"] or url_for("auth.entra_callback", _external=True)


@bp.route("/auth/entra/login")
def entra_login():
    ecfg = settings.current()["auth"]["entra"]
    if not ecfg["enabled"]:
        return redirect(url_for("auth.login"))
    try:
        auth_url, flow = get_sso_provider(ecfg).begin(_redirect_uri(ecfg))
    except Exception:  # p. ej. MSAL sin conexión al descubrir la autoridad
        current_app.logger.exception("No se pudo iniciar el login SSO")
        flash("No se pudo contactar con el proveedor de identidad.", "error")
        return redirect(url_for("auth.login"))
    session["entra_flow"] = flow
    session["entra_next"] = request.args.get("next", "")
    return redirect(auth_url)


@bp.route("/auth/entra/callback")
def entra_callback():
    ecfg = settings.current()["auth"]["entra"]
    if not ecfg["enabled"]:
        return redirect(url_for("auth.login"))
    ip = client_ip()
    flow = session.pop("entra_flow", None)
    next_url = session.pop("entra_next", "")
    if not flow:
        flash("La sesión de inicio expiró. Inténtalo de nuevo.", "error")
        return redirect(url_for("auth.login"))
    try:
        claims = get_sso_provider(ecfg, flow.get("provider")).complete(flow, request.args.to_dict())
        user = accounts.login_with_claims(ecfg, claims, ip=ip)
    except SSOError as exc:
        current_app.logger.warning("SSO error: %s", exc)
        audit.log("login_failed", ip=ip, detail=f"entra:{exc.code}")
        flash("No se pudo iniciar sesión con Microsoft.", "error")
        return redirect(url_for("auth.login"))
    except accounts.AccountError as exc:
        audit.log("login_denied", ip=ip, detail=f"entra:{exc.code}")
        flash(exc.message, "error")
        return redirect(url_for("auth.login"))

    start_session(user)
    audit.log("login", username=user["username"], ip=ip, detail="entra")
    return redirect(safe_next(next_url))

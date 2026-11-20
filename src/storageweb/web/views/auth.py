"""Rutas de inicio/cierre de sesión: el formulario (métodos con contraseña) y el SSO de cada método.

Nada aquí depende de un proveedor concreto: ``/auth/<método>/login`` y ``/auth/<método>/callback``
sirven para cualquier método SSO registrado (``providers.AuthMethod``). Para Entra ID la dirección
de vuelta es ``/auth/entra/callback``.
"""
from __future__ import annotations

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ... import providers
from ...core import accounts, ipban, mfa
from ...core import shares as share_core
from ...db.repositories import audit, sessions as session_repo, users
from ...i18n import _
from ...i18n import normalize as normalize_locale
from ...providers import SSOError
from ...settings import ConfigError, runtime_view
from ..context import external_url, get_db, invalidate_settings, runtime, settings, throttle
from ..guards import audit_event, client_ip, end_session, safe_next, start_session
from . import mfa as mfa_views

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
    if request.method == "GET" and not request.args.get("manual"):
        # Entrar directamente con el proveedor SSO (en un equipo unido a Entra ID, sin escribir nada).
        # Tras salir o tras un error se vuelve con «?manual=1»: si no, se entraría otra vez en bucle.
        auto = next((m for m in _enabled(cfg, sso=True) if m.section(cfg).get("auto_login")), None)
        if auto is not None:
            return redirect(url_for("auth.sso_login", method=auto.key, next=next_url))

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
            step = mfa.needed(get_db(), cfg, user) if user else ""
            if step:
                # Falta el segundo factor: no hay sesión todavía (y el limitador no se reinicia hasta el código)
                return mfa_views.hold(user, username, next_url, step)
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
    # Tras un intento fallido con la cuenta local, el formulario sale desplegado y con el usuario escrito
    tried = request.method == "POST" and form_enabled
    return render_template("login.html", form_enabled=form_enabled, sso_buttons=buttons, next_url=next_url,
                           local_open=tried, username=(request.form.get("username") or "").strip() if tried else "")


@bp.route("/locale", methods=["POST"])
def change_locale():
    """Cambia el idioma: se guarda en la sesión y, si hay usuario, en su cuenta."""
    locale = normalize_locale(request.form.get("locale"))
    if locale:
        session["locale"] = locale
        if g.get("user") is not None:
            users.update(get_db(), g.user["id"], locale=locale)
        audit_event("preference_changed", None, f"locale={locale}")
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
        url = method.logout_url(method.section(cfg), external_url("auth.login", manual=1))
        if url:  # cerrar también la sesión en el proveedor
            return redirect(url)
    flash(_("You have signed out."), "info")
    return redirect(url_for("auth.login", manual=1))


def redirect_uri(key: str) -> str:
    """Dirección de vuelta del método: ``/auth/<método>/callback`` en la dirección pública (``network.public_url``)
    o, sin ella, en la dirección con la que entró el navegador. Nunca se guarda: así sigue a la dirección pública."""
    return external_url("auth.sso_callback", method=key)


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
        return redirect(url_for("auth.login", manual=1))
    section = m.section(cfg)
    try:
        auth_url, flow = m.begin(section, redirect_uri(m.key))
    except Exception:  # p. ej. MSAL sin conexión al descubrir la autoridad
        current_app.logger.exception("Could not start the SSO login")
        flash(_("Could not contact the identity provider."), "error")
        return redirect(url_for("auth.login", manual=1))
    session["sso"] = {"method": m.key, "flow": flow, "next": request.args.get("next", "")}
    return redirect(auth_url)


@bp.route("/auth/<method>/callback")
def sso_callback(method: str):
    m = _sso_method(method)
    cfg = settings()
    if not m.enabled(cfg):
        return redirect(url_for("auth.login", manual=1))
    ip = client_ip()
    pending = session.pop("sso", None) or {}
    if not pending.get("flow") or pending.get("method") != m.key:
        flash(_("The sign-in session expired. Try again."), "error")
        return redirect(url_for("auth.login", manual=1))
    try:
        user, identity = accounts.complete_sso(get_db(), cfg, m.key, pending["flow"], request.args.to_dict(), ip=ip,
                                               on_rename=_rename_in_shares)
    except SSOError as exc:
        current_app.logger.warning("SSO error: %s", exc)
        audit.log(get_db(), "login_failed", ip=ip, detail=f"{m.key}:{exc.code}")
        flash(_("Could not sign in with %(method)s.", method=m.label), "error")
        return redirect(url_for("auth.login", manual=1))
    except accounts.AccountError as exc:
        audit.log(get_db(), "login_denied", ip=ip, detail=f"{m.key}:{exc.code}")
        flash(exc.message, "error")
        return redirect(url_for("auth.login", manual=1))

    start_session(user, identity.session_id)
    audit.log(get_db(), "login", username=user["username"], ip=ip, detail=m.key)
    return redirect(safe_next(pending.get("next", "")))


def _rename_in_shares(old: str, new: str) -> None:
    """Una cuenta cambió de nombre al entrar (UPN nuevo): las carpetas compartidas que la nombraban pasan al
    nombre nuevo. Si esa lista está fijada en config.json no se puede: queda en la auditoría para hacerlo a mano."""
    base = runtime_view(settings())
    renamed = share_core.rename_user(base["storage"]["shares"], old, new)
    if renamed is None:
        return
    current = {**base, "storage": {**base["storage"], "shares": renamed}}
    try:
        runtime().save(get_db(), current, "system", strict=True, base=base)
    except ConfigError as exc:
        current_app.logger.warning("Shared folders still name %s: %s", old, exc)
        audit.log(get_db(), "user_rename_failed", username=new, detail=f"shares: {exc}"[:200])
        return
    invalidate_settings()


@bp.route("/auth/<method>/frontchannel-logout")
def sso_frontchannel_logout(method: str):
    """Cierre de sesión de canal frontal: el proveedor (Entra ID) carga esta dirección en un marco invisible cuando
    la persona cierra sesión en él, con su sesión (``sid``). Se cierran las sesiones de StorageWeb iniciadas con
    ella. No usa la cookie (en un marco de otro sitio no llega); el ``sid`` lo genera el proveedor y no se adivina."""
    m = _sso_method(method)
    provider_sid = m.frontchannel_session(m.section(settings()), request.args.to_dict())
    if provider_sid is None:
        abort(404)
    if provider_sid:
        for user in session_repo.delete_by_provider_sid(get_db(), m.key, provider_sid[:200]):
            audit.log(get_db(), "logout", username=user["username"], ip=client_ip(), detail=f"{m.key}:frontchannel")
    response = current_app.response_class("", mimetype="text/plain")
    response.headers["Cache-Control"] = "no-store"
    return response

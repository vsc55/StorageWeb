"""Autenticación: usuarios locales (SQLite), usuarios del sistema (PAM) y Microsoft Entra ID (SSO)."""
from __future__ import annotations

import sys
from urllib.parse import urlencode

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .security import safe_next

bp = Blueprint("auth", __name__)

# Hash ficticio para igualar tiempos cuando el usuario no existe
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


def _cfg() -> dict:
    return current_app.config["SW"]


def _client_ip() -> str:
    return request.remote_addr or "-"


def _start_session(user) -> None:
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["src"] = user["source"]


def load_current_user() -> None:
    g.user = None
    uid = session.get("uid")
    if uid is None:
        return
    user = db.get_user_by_id(uid)
    if user is None or not user["enabled"]:
        session.clear()
        return
    g.user = user


# --------------------------------------------------------------------------- PAM

def _pam_authenticate(username: str, password: str) -> list[str] | None:
    """Devuelve la lista de grupos del SO si las credenciales son válidas."""
    pcfg = _cfg()["auth"]["pam"]
    if not pcfg["enabled"] or sys.platform == "win32":
        return None
    try:
        import grp
        import pwd

        import pam  # python-pam
    except ImportError:
        current_app.logger.error("auth.pam activado pero falta el paquete python-pam")
        return None
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return None
    if not pam.pam().authenticate(username, password, service=pcfg["service"]):
        return None
    groups = {grp.getgrgid(pw.pw_gid).gr_name}
    groups.update(gr.gr_name for gr in grp.getgrall() if username in gr.gr_mem)
    groups = sorted(x.lower() for x in groups)
    allowed = {x.lower() for x in pcfg["allowed_groups"]}
    if allowed and not allowed.intersection(groups):
        current_app.logger.warning("Usuario PAM %s no pertenece a allowed_groups", username)
        return None
    return groups


def _pam_home(username: str) -> str | None:
    if not _cfg()["auth"]["pam"]["use_system_home"]:
        return None
    import pwd
    return pwd.getpwnam(username).pw_dir


# --------------------------------------------------------------------------- formulario

@bp.route("/login", methods=["GET", "POST"])
def login():
    cfg = _cfg()
    if g.get("user"):
        return redirect(safe_next(request.args.get("next")))
    form_enabled = cfg["auth"]["local"]["enabled"] or cfg["auth"]["pam"]["enabled"]
    entra_enabled = cfg["auth"]["entra"]["enabled"]
    next_url = request.values.get("next", "")

    if request.method == "POST" and form_enabled:
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = _client_ip()
        throttle = current_app.extensions["sw_throttle"]

        if not username or not password:
            flash("Introduce usuario y contraseña.", "error")
        elif throttle.is_blocked(ip, username):
            db.audit("login_blocked", username=username, ip=ip)
            flash("Demasiados intentos fallidos. Espera unos minutos.", "error")
        else:
            user = _authenticate_form(username, password)
            if user:
                throttle.success(ip, username)
                _start_session(user)
                db.audit("login", username=user["username"], ip=ip, detail=user["source"])
                return redirect(safe_next(next_url))
            throttle.failure(ip, username)
            db.audit("login_failed", username=username, ip=ip)
            flash("Usuario o contraseña incorrectos.", "error")

    return render_template("login.html", form_enabled=form_enabled, entra_enabled=entra_enabled,
                           entra_label=cfg["auth"]["entra"]["button_label"], next_url=next_url)


def _authenticate_form(username: str, password: str):
    cfg = _cfg()
    user = db.get_user_by_username(username)

    if user is not None and user["source"] == "local":
        if not cfg["auth"]["local"]["enabled"]:
            return None
        if user["enabled"] and check_password_hash(user["password_hash"] or _DUMMY_HASH, password):
            db.touch_login(user["id"])
            return user
        return None

    if user is not None and user["source"] == "entra":
        check_password_hash(_DUMMY_HASH, password)
        return None  # los usuarios de Entra solo entran por SSO

    groups = _pam_authenticate(username, password)
    if groups is None:
        if user is None:
            check_password_hash(_DUMMY_HASH, password)
        return None
    if user is None:
        conn = db.get_db()
        uid = db.create_user(conn, username=username, source="pam", groups=groups,
                             home_path=_pam_home(username))
        user = db.get_user_by_id(uid)
    if not user["enabled"]:
        return None
    db.touch_login(user["id"], groups=groups)
    return db.get_user_by_id(user["id"])


@bp.route("/logout", methods=["POST"])
def logout():
    user = g.get("user")
    src = session.get("src")
    if user:
        db.audit("logout", username=user["username"], ip=_client_ip())
    session.clear()
    ecfg = _cfg()["auth"]["entra"]
    if src == "entra" and ecfg["enabled"] and ecfg["single_logout"]:
        params = urlencode({"post_logout_redirect_uri": url_for("auth.login", _external=True)})
        return redirect(f"https://login.microsoftonline.com/{ecfg['tenant_id']}/oauth2/v2.0/logout?{params}")
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))


# --------------------------------------------------------------------------- Entra ID

def _msal_app():
    import msal

    ecfg = _cfg()["auth"]["entra"]
    return msal.ConfidentialClientApplication(
        ecfg["client_id"],
        authority=f"https://login.microsoftonline.com/{ecfg['tenant_id']}",
        client_credential=ecfg["client_secret"],
    )


def _entra_redirect_uri() -> str:
    return _cfg()["auth"]["entra"]["redirect_uri"] or url_for("auth.entra_callback", _external=True)


@bp.route("/auth/entra/login")
def entra_login():
    ecfg = _cfg()["auth"]["entra"]
    if not ecfg["enabled"]:
        return redirect(url_for("auth.login"))
    next_url = request.args.get("next", "")
    flow = _msal_app().initiate_auth_code_flow(
        scopes=ecfg["scopes"], redirect_uri=_entra_redirect_uri(), prompt="select_account"
    )
    session["entra_flow"] = flow
    session["entra_next"] = next_url
    return redirect(flow["auth_uri"])


@bp.route("/auth/entra/callback")
def entra_callback():
    ecfg = _cfg()["auth"]["entra"]
    if not ecfg["enabled"]:
        return redirect(url_for("auth.login"))
    ip = _client_ip()
    flow = session.pop("entra_flow", None)
    next_url = session.pop("entra_next", "")
    if not flow:
        flash("La sesión de inicio expiró. Inténtalo de nuevo.", "error")
        return redirect(url_for("auth.login"))
    try:
        result = _msal_app().acquire_token_by_auth_code_flow(flow, request.args.to_dict())
    except ValueError:  # state no coincide / CSRF
        flash("Respuesta de inicio de sesión no válida.", "error")
        return redirect(url_for("auth.login"))
    if "error" in result:
        current_app.logger.warning("Entra ID error: %s %s", result.get("error"),
                                   result.get("error_description"))
        db.audit("login_failed", ip=ip, detail=f"entra:{result.get('error')}")
        flash("No se pudo iniciar sesión con Microsoft.", "error")
        return redirect(url_for("auth.login"))

    claims = result.get("id_token_claims") or {}
    tenant = ecfg["tenant_id"].lower()
    if tenant not in ("common", "organizations") and claims.get("tid", "").lower() != tenant:
        flash("Tu cuenta no pertenece a la organización permitida.", "error")
        return redirect(url_for("auth.login"))

    oid = claims.get("oid") or claims.get("sub")
    raw_username = (claims.get(ecfg["username_claim"]) or claims.get("email") or "").strip().lower()
    if not oid or not raw_username:
        flash("La cuenta de Microsoft no devolvió un identificador válido.", "error")
        return redirect(url_for("auth.login"))
    username = raw_username.split("@")[0] if ecfg["strip_domain"] else raw_username

    groups = sorted({str(x).lower() for x in claims.get("groups", [])} |
                    {str(x).lower() for x in claims.get("roles", [])})
    allowed = {x.lower() for x in ecfg["allowed_groups"]}
    if allowed and not allowed.intersection(groups):
        if "_claim_names" in claims and "groups" in claims.get("_claim_names", {}):
            current_app.logger.warning("Overage de grupos para %s; usa App Roles o "
                                       "'grupos asignados a la aplicación'", username)
        db.audit("login_denied", username=username, ip=ip, detail="entra:group")
        flash("Tu cuenta no tiene permiso para acceder a esta aplicación.", "error")
        return redirect(url_for("auth.login"))

    user = db.get_user_by_external("entra", oid)
    if user is None:
        existing = db.get_user_by_username(username)
        if existing is not None:
            # Nunca vincular automáticamente con una cuenta local/PAM con el mismo nombre
            current_app.logger.warning("Conflicto: %s ya existe con origen %s", username, existing["source"])
            flash("Ya existe una cuenta con ese nombre. Contacta con el administrador.", "error")
            return redirect(url_for("auth.login"))
        uid = db.create_user(db.get_db(), username=username, source="entra", external_id=oid,
                             display_name=claims.get("name"), email=claims.get("email") or raw_username,
                             groups=groups)
        user = db.get_user_by_id(uid)
        db.audit("user_provisioned", username=username, ip=ip, detail="entra")
    if not user["enabled"]:
        flash("Tu cuenta está deshabilitada.", "error")
        return redirect(url_for("auth.login"))

    db.touch_login(user["id"], display_name=claims.get("name"), groups=groups)
    _start_session(user)
    db.audit("login", username=user["username"], ip=ip, detail="entra")
    return redirect(safe_next(next_url))

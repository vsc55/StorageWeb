"""Verificación en dos pasos en la web: el paso intermedio del inicio de sesión y la tarjeta de *Mi perfil*.

**Un inicio de sesión que debe el segundo factor no es una sesión.** No hay fila en ``sessions`` ni ``uid`` en la
cookie: solo una nota firmada (``mfa_pending``) con quién está a medio entrar, a dónde iba y hasta cuándo. Hasta que
el código verifica, la petición es anónima por no tener sesión, y ninguna guarda tiene que acordarse de nada. Al
verificar se vuelve a leer la cuenta (entre la contraseña y el código pudo desactivarse) y se abre la sesión.

Los intentos fallidos cuentan en el mismo limitador que las contraseñas, y la contraseña correcta NO lo reinicia
mientras falte el código: si no, quien tenga la contraseña podría probar códigos sin fin volviendo a escribirla.
"""
from __future__ import annotations

import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from ...core import ipban, mfa
from ...db.repositories import audit, users
from ...i18n import _
from ..context import get_db, runtime, settings, throttle
from ..guards import audit_event, client_ip, clear_session, login_required, safe_next, start_session

bp = Blueprint("mfa", __name__)

HOLD_SECONDS = 300          # cuánto vive el inicio de sesión aparcado esperando el código
_PENDING = "mfa_pending"    # la nota en la cookie
_CODES = "mfa_new_recovery" # los códigos de recuperación recién generados, para enseñarlos una vez


def _issuer() -> str:
    return settings()["app_name"] or "StorageWeb"


def _key():
    return runtime().secrets_key


# --------------------------------------------------------------------------- el paso intermedio del inicio de sesión

def hold(user, typed_username: str, next_url: str, step: str):
    """Aparca un inicio de sesión con contraseña correcta que aún debe el segundo factor y lleva a su página."""
    clear_session()
    session[_PENDING] = {"user": user["id"], "name": typed_username, "next": next_url, "step": step,
                         "exp": time.time() + HOLD_SECONDS}
    return redirect(url_for("mfa.login_enrol" if step == "enrol" else "mfa.login_verify"))


def _pending():
    """``(usuario, nota)`` del inicio de sesión aparcado, o ``None`` si no hay, caducó o la cuenta ya no vale."""
    held = session.get(_PENDING)
    if not held or held.get("exp", 0) < time.time():
        session.pop(_PENDING, None)
        return None
    user = users.get_by_id(get_db(), held["user"])
    if user is None or not user["enabled"]:
        session.pop(_PENDING, None)
        return None
    return user, held


def _expired():
    flash(_("The sign-in waited too long for the code. Sign in again."), "error")
    return redirect(url_for("auth.login", manual=1))


def _limiter():
    cfg = settings()
    limiter = throttle()
    limiter.configure(cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60)
    return limiter


def _failed(user, held: dict, stage: str, code: str) -> None:
    """Un código rechazado: auditoría con el detalle (vacío o equivocado) y lo mismo que una contraseña errónea."""
    ip = client_ip()
    audit.log(get_db(), "mfa_failed", username=user["username"], ip=ip,
              detail=f"stage={stage} error={'empty' if not code.strip() else 'bad_code'}")
    _limiter().failure(ip, held["name"])
    ipban.offense(get_db(), settings(), ip, "mfa_failed")
    # Lo mismo para vacío que para equivocado: cuál fue no se le dice a quien los está mandando
    flash(_("The code is not valid."), "error")


def _finish(user, held: dict, detail: str):
    """La segunda mitad de la autenticación: vuelve a leer la cuenta, abre la sesión y la registra."""
    user = users.get_by_id(get_db(), user["id"])
    if user is None or not user["enabled"]:
        session.pop(_PENDING, None)
        flash(_("Your account is disabled."), "error")
        return None
    _limiter().success(client_ip(), held["name"])
    start_session(user)   # también quita la nota
    audit.log(get_db(), "login", username=user["username"], ip=client_ip(), detail=detail)
    return user


@bp.route("/login/mfa", methods=["GET", "POST"])
def login_verify():
    found = _pending()
    if found is None:
        return _expired()
    user, held = found
    if request.method == "POST":
        code = request.form.get("code") or ""
        if _limiter().is_blocked(client_ip(), held["name"]):
            audit.log(get_db(), "login_blocked", username=user["username"], ip=client_ip(), detail="mfa")
            flash(_("Too many failed attempts. Wait a few minutes."), "error")
        else:
            kind = mfa.verify(get_db(), _key(), user, code)
            if kind:
                if _finish(user, held, f"{user['source']}+{kind}") is None:
                    return redirect(url_for("auth.login", manual=1))
                if kind == "recovery":
                    left = mfa.status(get_db(), user)["recovery_left"]
                    audit.log(get_db(), "mfa_recovery_used", username=user["username"], ip=client_ip(),
                              detail=f"left={left}")
                    flash(_("You used a recovery code (%(num)s left). Generate new ones in My profile.", num=left),
                          "error" if left <= 2 else "info")
                return redirect(safe_next(held.get("next")))
            _failed(user, held, "verify", code)
    return render_template("login_mfa.html", user=user)


@bp.route("/login/mfa/enrol", methods=["GET", "POST"])
def login_enrol():
    """Alta obligatoria dentro del inicio de sesión: la política exige el factor y la cuenta no lo tiene. Encender la
    política no deja fuera a nadie (tampoco al último administrador): lo configura aquí y entra."""
    found = _pending()
    if found is None:
        return _expired()
    user, held = found
    if mfa.enrolled(get_db(), user):        # ya lo tiene (otra pestaña): basta con el código
        session[_PENDING] = {**held, "step": "verify"}
        return redirect(url_for("mfa.login_verify"))
    if request.method == "POST":
        code = request.form.get("code") or ""
        if _limiter().is_blocked(client_ip(), held["name"]):
            flash(_("Too many failed attempts. Wait a few minutes."), "error")
        else:
            codes = mfa.enroll_confirm(get_db(), _key(), user, code)
            if codes:
                if _finish(user, held, f"{user['source']}+totp") is None:
                    return redirect(url_for("auth.login", manual=1))
                audit.log(get_db(), "mfa_enrolled", username=user["username"], ip=client_ip(), detail="forced")
                return _show_codes(codes, held.get("next"))
            _failed(user, held, "enrol", code)
    setup = mfa.pending_setup(get_db(), _key(), user, _issuer()) or mfa.enroll_begin(get_db(), _key(), user, _issuer())
    return render_template("login_mfa_enrol.html", user=user, setup=setup)


@bp.route("/login/mfa/cancel", methods=["POST"])
def login_cancel():
    held = session.get(_PENDING) or {}
    if held:
        audit_event("login_cancelled", held.get("name"), "mfa", username=held.get("name"))
    session.pop(_PENDING, None)
    return redirect(url_for("auth.login", manual=1))


# --------------------------------------------------------------------------- Mi perfil

def _own_account():
    """La cuenta de la sesión, si puede usar la verificación en dos pasos (las que entran con contraseña)."""
    if not mfa.applies(g.user):
        flash(_("You sign in with your organization's account: its two-step verification protects you."), "info")
        return None
    return g.user


def _back():
    return redirect(url_for("profile.section", section="security") + "#mfa")


def _show_codes(codes: list[str], next_url: str | None = None):
    """Los códigos de recuperación recién generados se enseñan una sola vez, en su propia página."""
    session[_CODES] = {"codes": codes, "next": next_url or ""}
    return redirect(url_for("mfa.codes"))


@bp.route("/profile/mfa/begin", methods=["POST"])
@login_required
def begin():
    user = _own_account()
    if user is None or mfa.enrolled(get_db(), user):
        return _back()
    mfa.enroll_begin(get_db(), _key(), user, _issuer())
    audit_event("mfa_enrol_started", user["username"])
    return redirect(url_for("mfa.setup"))


@bp.route("/profile/mfa", methods=["GET"])
@login_required
def setup():
    user = _own_account()
    setup_data = mfa.pending_setup(get_db(), _key(), user, _issuer()) if user else None
    if setup_data is None:
        return _back()
    return render_template("mfa_setup.html", setup=setup_data)


@bp.route("/profile/mfa/confirm", methods=["POST"])
@login_required
def confirm():
    user = _own_account()
    if user is None:
        return _back()
    code = request.form.get("code") or ""
    codes = mfa.enroll_confirm(get_db(), _key(), user, code)
    if not codes:
        audit_event("mfa_failed", None, f"stage=enrol error={'empty' if not code.strip() else 'bad_code'}")
        flash(_("The code is not valid. Check that the phone's clock is right and try again."), "error")
        return redirect(url_for("mfa.setup"))
    audit_event("mfa_enrolled", None, "self")
    return _show_codes(codes)


@bp.route("/profile/mfa/cancel", methods=["POST"])
@login_required
def cancel():
    user = _own_account()
    if user is not None and mfa.status(get_db(), user)["pending"]:
        mfa.disable(get_db(), user)          # solo el alta a medias: no había nada activo
    return _back()


def _proved(user) -> bool:
    """Cambiar algo del factor pide un código válido (de la aplicación o de recuperación): quien tenga la sesión
    abierta en un equipo ajeno no puede quitarlo ni llevarse códigos nuevos."""
    code = request.form.get("code") or ""
    kind = mfa.verify(get_db(), _key(), user, code)
    if not kind:
        audit_event("mfa_failed", None, f"stage=manage error={'empty' if not code.strip() else 'bad_code'}")
        flash(_("The code is not valid."), "error")
        return False
    if kind == "recovery":
        audit_event("mfa_recovery_used", None, f"left={mfa.status(get_db(), user)['recovery_left']}")
    return True


@bp.route("/profile/mfa/recovery", methods=["POST"])
@login_required
def regenerate():
    user = _own_account()
    if user is None or not mfa.enrolled(get_db(), user) or not _proved(user):
        return _back()
    codes = mfa.recovery_regenerate(get_db(), user)
    audit_event("mfa_recovery_regenerated")
    return _show_codes(codes)


@bp.route("/profile/mfa/disable", methods=["POST"])
@login_required
def disable():
    user = _own_account()
    if user is None or not mfa.enrolled(get_db(), user) or not _proved(user):
        return _back()
    mfa.disable(get_db(), user)
    audit_event("mfa_disabled", None, "self")
    if mfa.required(settings(), user):
        flash(_("Two-step verification is off. Your organization requires it: you will set it up again on your next "
                "sign-in."), "info")
    else:
        flash(_("Two-step verification is off."), "info")
    return _back()


@bp.route("/profile/mfa/codes")
@login_required
def codes():
    shown = session.pop(_CODES, None)
    if not shown:
        return _back()
    return render_template("mfa_codes.html", codes=shown["codes"], next_url=safe_next(shown.get("next")) or "")

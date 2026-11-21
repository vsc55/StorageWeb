"""Verificación en dos pasos en la web: el paso intermedio del inicio de sesión y la tarjeta de *Mi perfil*.

**Un inicio de sesión que debe el segundo factor no es una sesión.** No hay fila en ``sessions`` ni ``uid`` en la
cookie: solo una nota firmada (``mfa_pending``) con quién está a medio entrar, a dónde iba y hasta cuándo. Hasta que
el código (o la passkey) verifica, la petición es anónima por no tener sesión, y ninguna guarda tiene que acordarse de
nada. Al verificar se vuelve a leer la cuenta (entre la contraseña y el código pudo desactivarse) y se abre la sesión.

Los intentos fallidos cuentan en el mismo limitador que las contraseñas, y la contraseña correcta NO lo reinicia
mientras falte el código: si no, quien tenga la contraseña podría probar códigos sin fin volviendo a escribirla.

**Passkeys.** Las ceremonias van por JSON (``static/js/passkeys.js`` las traduce a ``navigator.credentials``): el
servidor emite un challenge, lo guarda en la cookie firmada con su propósito, la cuenta y su caducidad, y lo gasta al
primer intento, valga o no. El RP ID y el origen salen de ``network.public_url`` (:func:`core.mfa.passkey_scope`),
nunca de la petición.

**Cambiar los factores pide demostrar que eres tú** (un código o una passkey), no solo la sesión: quien la tenga abierta
en un equipo ajeno no puede quitarlos, añadir su propia passkey ni llevarse códigos nuevos. La prueba vale 5 minutos
(``mfa_proof`` en la cookie) para no pedirla en cada botón.
"""
from __future__ import annotations

import time

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from ...core import ipban, mfa
from ...core.mfa import webauthn
from ...db.repositories import audit, users
from ...i18n import _
from ..context import get_db, runtime, settings, throttle
from ..guards import audit_event, client_ip, clear_session, login_required, safe_next, start_session

bp = Blueprint("mfa", __name__)

HOLD_SECONDS = 300          # cuánto vive el inicio de sesión aparcado esperando el código
PROOF_SECONDS = 300         # cuánto vale haber demostrado el segundo factor para cambiarlo en Mi perfil
_PENDING = "mfa_pending"    # la nota en la cookie
_CODES = "mfa_new_recovery" # los códigos de recuperación recién generados, para enseñarlos una vez
_CHALLENGE = "mfa_challenge"
_PROOF = "mfa_proof"


def _issuer() -> str:
    return settings()["app_name"] or "StorageWeb"


def _key():
    return runtime().secrets_key


# --------------------------------------------------------------------------- piezas de las passkeys

def passkeys_available() -> bool:
    """Si este servidor puede ofrecer passkeys ahora (ajuste activado y dirección pública con nombre y HTTPS)."""
    return bool(mfa.passkey_scope(settings())[0])


def _issue(purpose: str, user) -> str:
    challenge = mfa.new_challenge()
    session[_CHALLENGE] = {"c": challenge, "for": purpose, "user": user["id"],
                           "exp": time.time() + mfa.CHALLENGE_SECONDS}
    return challenge


def _take(purpose: str, user) -> str:
    """El challenge emitido para esto y esta cuenta, gastado (una sola respuesta por challenge), o ``""``."""
    held = session.pop(_CHALLENGE, None) or {}
    if held.get("for") != purpose or held.get("user") != user["id"] or held.get("exp", 0) < time.time():
        return ""
    return str(held.get("c") or "")


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _raw(data: dict, name: str) -> bytes:
    return webauthn.b64u_decode(str(data.get(name) or ""))


def _error(message: str, status: int = 400, **extra):
    return jsonify({"error": message, **extra}), status


def _reason(reason: str) -> str:
    """El motivo de un rechazo como palabra para la auditoría (``error=signature_does_not_verify``)."""
    return "_".join(str(reason or "unknown").split())


def _register(user, purpose: str, data: dict) -> list[str]:
    """Verifica un registro de passkey con el challenge de ``purpose``; lanza :class:`mfa.PasskeyError`."""
    rp_id, origin = mfa.passkey_scope(settings())
    challenge = _take(purpose, user)
    if not rp_id or not challenge:
        raise mfa.PasskeyError("no challenge" if rp_id else "passkeys unavailable")
    return mfa.register_passkey(get_db(), user, attestation_object=_raw(data, "attestation_object"),
                                client_data_json=_raw(data, "client_data_json"), challenge=challenge,
                                rp_id=rp_id, origin=origin, name=str(data.get("name") or ""))


def _assert(user, purpose: str, data: dict) -> str:
    """Verifica una aserción con el challenge de ``purpose``; devuelve el nombre de la passkey o lanza."""
    rp_id, origin = mfa.passkey_scope(settings())
    challenge = _take(purpose, user)
    if not rp_id or not challenge:
        raise mfa.PasskeyError("no challenge" if rp_id else "passkeys unavailable")
    return mfa.verify_passkey(get_db(), user, credential_id=str(data.get("id") or ""),
                              auth_data=_raw(data, "authenticator_data"),
                              client_data_json=_raw(data, "client_data_json"), signature=_raw(data, "signature"),
                              challenge=challenge, rp_id=rp_id, origin=origin)


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


def _expired_json():
    flash(_("The sign-in waited too long for the code. Sign in again."), "error")
    return _error(_("The sign-in waited too long for the code. Sign in again."), 401,
                  redirect=url_for("auth.login", manual=1))


def _limiter():
    cfg = settings()
    limiter = throttle()
    limiter.configure(cfg["security"]["max_login_failures"], cfg["security"]["lockout_minutes"] * 60)
    return limiter


def _blocked(user, held: dict) -> bool:
    if _limiter().is_blocked(client_ip(), held["name"]):
        audit.log(get_db(), "login_blocked", username=user["username"], ip=client_ip(), detail="mfa")
        return True
    return False


def _failed(user, held: dict, stage: str, code: str = "", *, error: str = "", notify: bool = True) -> None:
    """Un código o una passkey rechazados: auditoría con el detalle y lo mismo que una contraseña errónea."""
    ip = client_ip()
    why = error or ("empty" if not code.strip() else "bad_code")
    audit.log(get_db(), "mfa_failed", username=user["username"], ip=ip, detail=f"stage={stage} error={why}")
    _limiter().failure(ip, held["name"])
    ipban.offense(get_db(), settings(), ip, "mfa_failed")
    if notify:
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
    start_session(user)   # también quita la nota, el challenge y la prueba
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
        if _blocked(user, held):
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
    state = mfa.status(get_db(), user)
    return render_template("login_mfa.html", user=user, mfa=state,
                           passkeys_on=bool(state["passkeys"]) and passkeys_available())


@bp.route("/login/mfa/passkey/options", methods=["POST"])
def login_passkey_options():
    found = _pending()
    if found is None:
        return _expired_json()
    user, held = found
    rp_id = mfa.passkey_scope(settings())[0]
    if not rp_id or not mfa.status(get_db(), user)["passkeys"]:
        return _error(_("Passkeys are not available on this server."))
    if _blocked(user, held):
        return _error(_("Too many failed attempts. Wait a few minutes."), 429)
    return jsonify(mfa.assertion_options(get_db(), user, rp_id=rp_id, challenge=_issue("login", user)))


@bp.route("/login/mfa/passkey", methods=["POST"])
def login_passkey():
    found = _pending()
    if found is None:
        return _expired_json()
    user, held = found
    if _blocked(user, held):
        return _error(_("Too many failed attempts. Wait a few minutes."), 429)
    try:
        _assert(user, "login", _body())
    except mfa.PasskeyError as exc:
        _failed(user, held, "passkey", error=_reason(exc.reason), notify=False)
        return _error(_("The passkey was not accepted."))
    if _finish(user, held, f"{user['source']}+passkey") is None:
        return jsonify({"redirect": url_for("auth.login", manual=1)})
    return jsonify({"redirect": safe_next(held.get("next"))})


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
            if codes is not None:
                if _finish(user, held, f"{user['source']}+totp") is None:
                    return redirect(url_for("auth.login", manual=1))
                audit.log(get_db(), "mfa_enrolled", username=user["username"], ip=client_ip(), detail="forced")
                return _show_codes(codes, held.get("next"))
            _failed(user, held, "enrol", code)
    setup = mfa.pending_setup(get_db(), _key(), user, _issuer()) or mfa.enroll_begin(get_db(), _key(), user, _issuer())
    return render_template("login_mfa_enrol.html", user=user, setup=setup, passkeys_on=passkeys_available())


@bp.route("/login/mfa/enrol/passkey/options", methods=["POST"])
def login_enrol_passkey_options():
    found = _pending()
    if found is None:
        return _expired_json()
    user, held = found
    if mfa.enrolled(get_db(), user):
        session[_PENDING] = {**held, "step": "verify"}
        return jsonify({"redirect": url_for("mfa.login_verify")})
    rp_id = mfa.passkey_scope(settings())[0]
    if not rp_id:
        return _error(_("Passkeys are not available on this server."))
    return jsonify(mfa.registration_options(get_db(), user, rp_id=rp_id, rp_name=_issuer(),
                                            challenge=_issue("enrol", user)))


@bp.route("/login/mfa/enrol/passkey", methods=["POST"])
def login_enrol_passkey():
    found = _pending()
    if found is None:
        return _expired_json()
    user, held = found
    if mfa.enrolled(get_db(), user):
        session[_PENDING] = {**held, "step": "verify"}
        return jsonify({"redirect": url_for("mfa.login_verify")})
    if _blocked(user, held):
        return _error(_("Too many failed attempts. Wait a few minutes."), 429)
    data = _body()
    try:
        codes = _register(user, "enrol", data)
    except mfa.PasskeyError as exc:
        _failed(user, held, "enrol", error=_reason(exc.reason), notify=False)
        return _error(_("The passkey could not be added."))
    if mfa.status(get_db(), user)["pending"]:
        mfa.remove_totp(get_db(), user)      # el alta de la app que quedó a medias en la misma página
    if _finish(user, held, f"{user['source']}+passkey") is None:
        return jsonify({"redirect": url_for("auth.login", manual=1)})
    audit.log(get_db(), "mfa_enrolled", username=user["username"], ip=client_ip(), detail="forced passkey")
    audit.log(get_db(), "passkey_added", username=user["username"], ip=client_ip(),
              target=mfa.clean_name(data.get("name") or "") or "Passkey")
    _keep_codes(codes, held.get("next"))
    return jsonify({"redirect": url_for("mfa.codes") if codes else safe_next(held.get("next"))})


@bp.route("/login/mfa/cancel", methods=["POST"])
def login_cancel():
    held = session.get(_PENDING) or {}
    if held:
        audit_event("login_cancelled", held.get("name"), "mfa", username=held.get("name"))
    session.pop(_PENDING, None)
    session.pop(_CHALLENGE, None)
    return redirect(url_for("auth.login", manual=1))


# --------------------------------------------------------------------------- Mi perfil

def _own_account(*, notify: bool = True):
    """La cuenta de la sesión, si puede usar la verificación en dos pasos (las que entran con contraseña)."""
    if not mfa.applies(g.user):
        if notify:
            flash(_("You sign in with your organization's account: its two-step verification protects you."), "info")
        return None
    return g.user


def _back_url() -> str:
    return url_for("profile.section", section="security") + "#mfa"


def _back():
    return redirect(_back_url())


def _keep_codes(codes: list[str], next_url: str | None = None) -> None:
    if codes:
        session[_CODES] = {"codes": codes, "next": next_url or ""}


def _show_codes(codes: list[str], next_url: str | None = None):
    """Los códigos de recuperación recién generados se enseñan una sola vez, en su propia página."""
    if not codes:
        return redirect(safe_next(next_url)) if next_url else _back()
    _keep_codes(codes, next_url)
    return redirect(url_for("mfa.codes"))


def proof_ok(user) -> bool:
    """Si esta sesión demostró el segundo factor hace menos de :data:`PROOF_SECONDS` (para *Mi perfil*)."""
    held = session.get(_PROOF) or {}
    return held.get("user") == user["id"] and held.get("exp", 0) > time.time()


def _grant_proof(user) -> None:
    session[_PROOF] = {"user": user["id"], "exp": time.time() + PROOF_SECONDS}


def _proved(user) -> bool:
    """Cambiar algo del segundo paso pide haberlo demostrado hace poco (:func:`proof_ok`) o un código válido en el
    mismo formulario (de la aplicación o de recuperación)."""
    if proof_ok(user):
        return True
    code = request.form.get("code") or ""
    kind = mfa.verify(get_db(), _key(), user, code)
    if not kind:
        audit_event("mfa_failed", None, f"stage=manage error={'empty' if not code.strip() else 'bad_code'}")
        flash(_("The code is not valid."), "error")
        return False
    if kind == "recovery":
        audit_event("mfa_recovery_used", None, f"left={mfa.status(get_db(), user)['recovery_left']}")
    _grant_proof(user)
    return True


def _may_add(user) -> bool:
    """Añadir un factor a una cuenta que ya tiene uno es añadir una forma de entrar: pide la prueba."""
    return not mfa.enrolled(get_db(), user) or proof_ok(user)


@bp.route("/profile/mfa/prove", methods=["POST"])
@login_required
def prove():
    user = _own_account()
    if user is not None and mfa.enrolled(get_db(), user) and _proved(user):
        flash(_("Confirmed: for the next few minutes you can change your two-step verification."), "info")
    return _back()


@bp.route("/profile/mfa/begin", methods=["POST"])
@login_required
def begin():
    user = _own_account()
    if user is None or mfa.has_totp(get_db(), user):
        return _back()
    if mfa.enrolled(get_db(), user) and not _proved(user):
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
    if codes is None:
        audit_event("mfa_failed", None, f"stage=enrol error={'empty' if not code.strip() else 'bad_code'}")
        flash(_("The code is not valid. Check that the phone's clock is right and try again."), "error")
        return redirect(url_for("mfa.setup"))
    audit_event("mfa_enrolled", None, "self")
    if not codes:
        flash(_("The authenticator app is ready. Your recovery codes have not changed."), "info")
    return _show_codes(codes)


@bp.route("/profile/mfa/cancel", methods=["POST"])
@login_required
def cancel():
    user = _own_account()
    if user is not None and mfa.status(get_db(), user)["pending"]:
        mfa.remove_totp(get_db(), user)      # solo el alta a medias de la app: lo demás sigue
    return _back()


@bp.route("/profile/mfa/recovery", methods=["POST"])
@login_required
def regenerate():
    user = _own_account()
    if user is None or not mfa.enrolled(get_db(), user) or not _proved(user):
        return _back()
    codes = mfa.recovery_regenerate(get_db(), user)
    audit_event("mfa_recovery_regenerated")
    return _show_codes(codes)


def _off_message(user) -> None:
    if mfa.enrolled(get_db(), user):
        return
    if mfa.required(settings(), user):
        flash(_("Two-step verification is off. Your organization requires it: you will set it up again on your next "
                "sign-in."), "info")
    else:
        flash(_("Two-step verification is off."), "info")


@bp.route("/profile/mfa/disable", methods=["POST"])
@login_required
def disable():
    """Quita TODO (la app, las passkeys y los códigos)."""
    user = _own_account()
    if user is None or not mfa.enrolled(get_db(), user) or not _proved(user):
        return _back()
    mfa.disable(get_db(), user)
    session.pop(_PROOF, None)
    audit_event("mfa_disabled", None, "self")
    _off_message(user)
    return _back()


@bp.route("/profile/mfa/totp/remove", methods=["POST"])
@login_required
def totp_remove():
    """Quita solo la app de códigos (las passkeys siguen)."""
    user = _own_account()
    if user is None or not mfa.has_totp(get_db(), user) or not _proved(user):
        return _back()
    mfa.remove_totp(get_db(), user)
    audit_event("mfa_disabled", None, "self app")
    if mfa.enrolled(get_db(), user):
        flash(_("The authenticator app was removed. Your passkeys still protect the account."), "info")
    _off_message(user)
    return _back()


@bp.route("/profile/mfa/passkey/options", methods=["POST"])
@login_required
def passkey_options():
    """El challenge de una ceremonia de *Mi perfil*: ``{"for": "register"}`` (añadir una) o ``"prove"`` (demostrar
    que eres tú con una que ya tienes)."""
    user = _own_account(notify=False)
    rp_id = mfa.passkey_scope(settings())[0]
    if user is None or not rp_id:
        return _error(_("Passkeys are not available on this server."))
    if _body().get("for") == "prove":
        if not mfa.status(get_db(), user)["passkeys"]:
            return _error(_("Passkeys are not available on this server."))
        return jsonify(mfa.assertion_options(get_db(), user, rp_id=rp_id, challenge=_issue("prove", user)))
    if not _may_add(user):
        return _error(_("Confirm it is you first (a code or a passkey)."), 403, redirect=_back_url())
    return jsonify(mfa.registration_options(get_db(), user, rp_id=rp_id, rp_name=_issuer(),
                                            challenge=_issue("register", user)))


@bp.route("/profile/mfa/passkey/register", methods=["POST"])
@login_required
def passkey_register():
    user = _own_account(notify=False)
    if user is None:
        return _error(_("Passkeys are not available on this server."))
    if not _may_add(user):
        session.pop(_CHALLENGE, None)
        return _error(_("Confirm it is you first (a code or a passkey)."), 403, redirect=_back_url())
    data = _body()
    first = not mfa.enrolled(get_db(), user)
    try:
        codes = _register(user, "register", data)
    except mfa.PasskeyError as exc:
        audit_event("mfa_failed", None, f"stage=enrol error={_reason(exc.reason)}")
        return _error(_("The passkey could not be added."))
    name = mfa.clean_name(data.get("name") or "") or "Passkey"
    audit_event("passkey_added", name)
    if first:
        audit_event("mfa_enrolled", None, "self passkey")
        _grant_proof(user)      # acaba de demostrarla: puede seguir (ponerle nombre, añadir otra) sin pedirla
    flash(_("Passkey «%(name)s» added.", name=name), "info")
    _keep_codes(codes)
    return jsonify({"redirect": url_for("mfa.codes") if codes else _back_url()})


@bp.route("/profile/mfa/passkey/prove", methods=["POST"])
@login_required
def passkey_prove():
    user = _own_account(notify=False)
    if user is None:
        return _error(_("Passkeys are not available on this server."))
    try:
        _assert(user, "prove", _body())
    except mfa.PasskeyError as exc:
        audit_event("mfa_failed", None, f"stage=manage error={_reason(exc.reason)}")
        return _error(_("The passkey was not accepted."))
    _grant_proof(user)
    flash(_("Confirmed: for the next few minutes you can change your two-step verification."), "info")
    return jsonify({"redirect": _back_url()})


@bp.route("/profile/mfa/passkey/<int:passkey_id>/rename", methods=["POST"])
@login_required
def passkey_rename(passkey_id: int):
    user = _own_account()
    if user is None:
        return _back()
    old = mfa.passkey_name(get_db(), user, passkey_id)
    name = request.form.get("name") or ""
    if old and mfa.rename_passkey(get_db(), user, passkey_id, name):
        audit_event("passkey_renamed", mfa.clean_name(name), f"from={old}")
    return _back()


@bp.route("/profile/mfa/passkey/<int:passkey_id>/remove", methods=["POST"])
@login_required
def passkey_remove(passkey_id: int):
    user = _own_account()
    if user is None:
        return _back()
    name = mfa.passkey_name(get_db(), user, passkey_id)
    if not name or not _proved(user):
        return _back()
    mfa.remove_passkey(get_db(), user, passkey_id)
    audit_event("passkey_removed", name)
    flash(_("Passkey «%(name)s» removed.", name=name), "info")
    _off_message(user)
    return _back()


@bp.route("/profile/mfa/codes")
@login_required
def codes():
    shown = session.pop(_CODES, None)
    if not shown:
        return _back()
    return render_template("mfa_codes.html", codes=shown["codes"], next_url=safe_next(shown.get("next")) or "")

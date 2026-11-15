"""Entra ID: probar la conexión, asistente y registro de la aplicación con código de dispositivo."""
from __future__ import annotations

import re
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for

from ....core import accounts
from ....core.network import LOOPBACK
from ....core.permissions import ROLE_LABELS
from ....i18n import _, _l
from ....providers.entra import check as entra_check
from ....providers.entra import register as entra_register
from ....settings import ROLES
from ...context import external_url, get_db, runtime, settings
from ...guards import admin_required, audit_event, safe_next
from ... import search
from . import bp
from ....providers.entra import method as entra_method
from ....providers.entra.sso import SSO_PROVIDERS
from ....settings import ConfigError
from ..auth import redirect_uri as sso_redirect_uri
from . import auth_forms
from .common import back, checked, form_int, save_partial, split_list


WIZARD_STEPS = (1, 2, 3, 4)


def redirect_uri(_ecfg: dict | None = None) -> str:
    """La dirección de vuelta: se calcula siempre (``auth.redirect_uri``), nunca se guarda."""
    return sso_redirect_uri("entra")


def entra_connection() -> dict:
    f = request.form
    data = {"tenant_id": f.get("entra_tenant_id", "").strip(), "client_id": f.get("entra_client_id", "").strip()}
    if f.get("entra_client_secret", "").strip():  # vacío = conservar el actual
        data["client_secret"] = f["entra_client_secret"].strip()
        mark_new_secret()
    return data


# Un secreto recién creado tarda en valer en todos los servidores de Microsoft (a veces un minuto): durante este
# tiempo, que lo rechace no se da como error sino como «activándose», y el asistente vuelve a comprobarlo solo.
SECRET_SETTLE_SECONDS = 180


def mark_new_secret() -> None:
    session["entra_secret_at"] = time.time()


def secret_is_new() -> bool:
    at = session.get("entra_secret_at")
    return isinstance(at, (int, float)) and 0 <= time.time() - at < SECRET_SETTLE_SECONDS


# --------------------------------------------------------------------------- tarjeta de la página «Inicio de sesión»

def _role_mappings() -> dict:
    f = request.form
    if "entra_role_mappings" in f:  # formato de texto «grupo = rol», una línea por mapeo
        mappings = {}
        for n, line in enumerate(f.get("entra_role_mappings", "").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, role = line.rpartition("=")
            if not sep or not key.strip():
                raise ConfigError(_("Role mapping, line %(line)s: use the format «group = role»", line=n),
                                  "auth.entra.role_mappings")
            mappings[key.strip()] = role.strip()
        return mappings
    return {grp.strip(): role for grp, role in zip(f.getlist("mapping_group"), f.getlist("mapping_role"))
            if grp.strip()}


def _secret_expires(date_text: str) -> str:
    """La fecha del formulario (AAAA-MM-DD). Si es el mismo día que la guardada, se conserva la hora exacta."""
    current = settings()["auth"]["entra"].get("secret_expires", "")
    if current and current[:10] == date_text:
        return current
    return date_text


@auth_forms.form_parser("entra")
def _form(method) -> dict:
    f = request.form
    return {
        **entra_connection(),
        "enabled": checked("entra_enabled"),
        "provider": f.get("entra_provider", "oauth2"),
        "scopes": f.get("entra_scopes", "").split(),
        "button_label": f.get("entra_button_label", "").strip(),
        "username_claim": f.get("entra_username_claim", "").strip() or "preferred_username",
        "strip_domain": checked("entra_strip_domain"),
        "allowed_groups": split_list(f.get("entra_allowed_groups", "")),
        "auto_provision": checked("entra_auto_provision"),
        "default_role": f.get("entra_default_role", "user"),
        "role_mappings": _role_mappings(),
        "sync_role_on_login": checked("entra_sync_role_on_login"),
        "directory_sync_minutes": form_int("entra_directory_sync_minutes", "auth.entra.directory_sync_minutes",
                                           _("Check accounts against Entra ID every (minutes)")),
        "single_logout": checked("entra_single_logout"),
        "auto_login": checked("entra_auto_login"),
        "authorize_url": f.get("entra_authorize_url", "").strip(),
        "token_url": f.get("entra_token_url", "").strip(),
        "issuer": f.get("entra_issuer", "").strip(),
        "logout_url": f.get("entra_logout_url", "").strip(),
        "timeout_seconds": form_int("entra_timeout_seconds", "auth.entra.timeout_seconds", _("Timeout")),
        "secret_expires": _secret_expires(f.get("entra_secret_expires", "").strip()),
    }


GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def group_lookup(*ids) -> dict:
    """Para los campos de grupos de Entra ID: la URL del buscador por nombre ("" si la aplicación no puede leer el
    directorio) y los nombres de los Object IDs dados (``{id en minúsculas: nombre}``; los que no se sepan, no)."""
    from ..groups import _directories, directory_names  # noqa: PLC0415 (vista hermana; evita un import circular)
    search = next((url_for("groups.directory_search", method=m.key)
                   for m, d in _directories("entra") if d.configured()), "")
    wanted = sorted({str(i).lower() for i in ids if i and GUID_RE.match(str(i))})
    return {"group_search": search, "group_names": directory_names(wanted, only="entra") if wanted else {}}


@auth_forms.page_context("entra")
def _card(cfg: dict) -> dict:
    ecfg = cfg["auth"]["entra"]
    check = session.get("entra_check")
    return {"providers": list(SSO_PROVIDERS), "secret_set": bool(settings()["auth"]["entra"].get("client_secret")),
            "secret_days": entra_method.secret_days(ecfg) if ecfg.get("secret_expires") else None,
            "entra_check": check, "entra_check_ok": entra_check.summary(check["results"]) if check else None,
            "entra_repairable": entra_check.repairs(check["results"]) if check else None,
            "entra_portal": entra_register.portal_url(ecfg["client_id"])
            if ecfg.get("client_id") and not any(ecfg.get(k) for k in ("authorize_url", "token_url", "issuer")) else "",
            "redirect_default": redirect_uri(),
            **group_lookup(*ecfg.get("role_mappings", {}).keys(), *ecfg.get("allowed_groups", []))}


# --------------------------------------------------------------------------- Entra ID: prueba y asistente

def _run_check() -> dict:
    ecfg = settings()["auth"]["entra"]
    result = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "results": entra_check.check(ecfg, redirect_uri(ecfg), secret_is_new=secret_is_new(),
                                           last_signin=accounts.last_signin_scopes(get_db(), "entra"))}
    session["entra_check"] = result
    return result


@bp.route("/entra/test", methods=["POST"])
@admin_required
def entra_test():
    result = _run_check()
    ok = entra_check.summary(result["results"])
    flash(_("Connection with Entra ID checked: everything is correct.") if ok else
          _("Connection with Entra ID checked: there are problems, see the details."), "info" if ok else "error")
    target = request.form.get("next")
    return redirect(safe_next(target) if target else url_for("settings.section", name="auth"))


@bp.route("/entra/setup", methods=["GET", "POST"])
@admin_required
def entra_setup():
    step = request.values.get("step", 1, type=int)
    step = step if step in WIZARD_STEPS else 1
    error = None
    if request.method == "POST":
        f = request.form
        if step == 2:
            draft, error = save_partial(lambda: {"auth": {"entra": entra_connection()}})
        elif step == 3:
            def _users():
                mappings = dict(settings()["auth"]["entra"]["role_mappings"])
                admin_group = f.get("admin_group", "").strip()
                if admin_group:
                    mappings[admin_group.lower()] = "admin"
                return {"auth": {"entra": {"auto_provision": f.get("provisioning") == "auto",
                                           "allowed_groups": split_list(f.get("allowed_groups", "")),
                                           "default_role": f.get("default_role", "user"),
                                           "role_mappings": mappings}}}
            draft, error = save_partial(_users)
        elif step == 4:
            draft, error = save_partial(lambda: {"auth": {"entra": {"enabled": True}}})
            if not error:
                audit_event("settings_updated", None, "entra_setup")
                flash(_("Entra ID enabled. Users can now sign in with Microsoft."), "info")
                return redirect(url_for("settings.section", name="auth"))
        if not error:
            audit_event("settings_updated", None, f"entra_setup:{step}")
            return redirect(url_for("settings.entra_setup", step=step + 1))
    ecfg = settings()["auth"]["entra"]
    check = None
    if step == 4 and request.method == "GET" and ecfg.get("tenant_id") and ecfg.get("client_id"):
        check = _run_check()
    registered = session.pop("entra_registered", None) if step == 4 else None
    pending = bool(check) and any(r.get("pending") for r in check["results"])
    repairable = entra_check.repairs(check["results"]) if check else None
    admin_group = next((k for k, v in ecfg["role_mappings"].items() if v == "admin"), "")
    lookup = group_lookup(admin_group, *ecfg["allowed_groups"]) if step == 3 else {"group_search": "", "group_names": {}}
    return render_template("admin/settings/entra_setup.html", step=step, steps=WIZARD_STEPS, en=ecfg,
                           registered=registered, check_pending=pending, repairable=repairable,
                           redirect_uri=redirect_uri(ecfg), error=error, error_field=error.field if error else None,
                           check=check, check_ok=entra_check.summary(check["results"]) if check else None,
                           secret_set=bool(ecfg.get("client_secret")), ROLES=ROLES, ROLE_LABELS=ROLE_LABELS,
                           admin_group=admin_group, **lookup), \
        400 if error else 200


# --------------------------------------------------------------------------- Entra ID: registro automático

# Inicios de sesión con código de dispositivo en curso. En memoria del proceso a propósito: el
# device_code no sale del servidor (la sesión solo guarda una clave aleatoria) y un reinicio los
# descarta, que es lo esperable para algo que caduca en 15 minutos.
_FLOWS: dict[str, dict] = {}
_FLOWS_LOCK = threading.Lock()
SLOW_DOWN_STEP, MAX_INTERVAL = 5, 30


def _register_flow() -> tuple[str | None, dict | None]:
    key = session.get("entra_register")
    with _FLOWS_LOCK:
        for k in [k for k, f in _FLOWS.items() if time.time() > f["expires_at"]]:
            _FLOWS.pop(k, None)
        flow = _FLOWS.get(key) if key else None
    if flow and flow["user_id"] != g.user["id"]:
        flow = None
    return key, flow


def _drop_flow(key: str | None) -> None:
    with _FLOWS_LOCK:
        _FLOWS.pop(key, None)
    session.pop("entra_register", None)


def _register_target() -> tuple[str, bool]:
    """Redirect URI que se registrará y si Entra ID la aceptará (HTTPS o localhost)."""
    uri = redirect_uri()
    parts = urlsplit(uri)
    return uri, parts.scheme == "https" or parts.hostname in LOOPBACK


def frontchannel_logout_url() -> str:
    """URL de cierre de sesión de canal frontal que se registra en Entra ID (Autenticación → Web)."""
    return external_url("auth.sso_frontchannel_logout", method="entra")


@bp.route("/entra/register", methods=["GET", "POST"])
@admin_required
def entra_register_page():
    redirect_uri, https_ok = _register_target()
    key, flow = _register_flow()
    if request.method == "POST":
        if not https_ok:
            flash(_("Entra ID only accepts HTTPS return addresses: set the public name in Network and HTTPS."),
                  "error")
            return redirect(url_for("settings.entra_register_page"))
        options = {"name": request.form.get("app_name", "").strip() or settings()["app_name"],
                   "redirect_uri": redirect_uri, "logout_url": frontchannel_logout_url(),
                   "app_roles": checked("app_roles"), "group_claims": checked("group_claims"),
                   "require_assignment": checked("require_assignment"), "group_read": checked("group_read")}
        return _start_flow("register", options)
    return render_template("admin/settings/entra_register.html", flow=flow, redirect_uri=redirect_uri,
                           https_ok=https_ok, app_name=settings()["app_name"],
                           expires_in=int(flow["expires_at"] - time.time()) if flow else 0)


FLOW_WRITES = {"register": ("auth.entra.tenant_id", "auth.entra.client_id", "auth.entra.client_secret",
                            "auth.entra.secret_expires"),
               "rotate": ("auth.entra.client_secret", "auth.entra.secret_expires"),
               "repair": ("auth.entra.client_secret", "auth.entra.secret_expires")}  # solo si crea secreto


def _start_flow(kind: str, options: dict):
    """Pide un código de dispositivo y aparca el flujo (``register``, ``rotate``, ``grant_groups`` o ``repair``)."""
    back = url_for("settings.section", name="auth") if kind != "register" else url_for("settings.entra_register_page")
    # No se empieza si el resultado no se va a poder guardar (campos fijados en config.json o el entorno)
    writes = () if kind == "repair" and not options.get("new_secret") else FLOW_WRITES.get(kind, ())
    for path in writes:
        if runtime().lock_of(path):
            flash(runtime().lock_message(path), "error")
            return redirect(back)
    key, _flow = _register_flow()
    try:
        code = entra_register.device_start()
    except entra_register.RegisterError as exc:
        flash(_("Could not start the sign-in with Microsoft: %(error)s", error=exc), "error")
        return redirect(url_for("settings.section", name="auth") if kind != "register"
                        else url_for("settings.entra_register_page"))
    _drop_flow(key)
    key = secrets.token_urlsafe(16)
    with _FLOWS_LOCK:
        _FLOWS[key] = {"kind": kind, "device_code": code["device_code"], "user_code": code["user_code"],
                       "verification_uri": code.get("verification_uri", "https://microsoft.com/devicelogin"),
                       "expires_at": time.time() + int(code.get("expires_in", 900)),
                       "interval": int(code.get("interval", 5)), "options": options, "user_id": g.user["id"]}
    session["entra_register"] = key
    return redirect(url_for("settings.entra_register_page"))


def _existing_client_id() -> str:
    client_id = settings()["auth"]["entra"].get("client_id", "")
    if not client_id:
        abort(400, description=_("There is no Client ID configured."))
    return client_id


@bp.route("/entra/rotate", methods=["POST"])
@admin_required
def entra_rotate():
    return _start_flow("rotate", {"client_id": _existing_client_id()})


@bp.route("/entra/repair", methods=["POST"])
@admin_required
def entra_repair():
    """«Reparar automáticamente»: tras iniciar sesión con Microsoft, arregla lo que la comprobación encontró mal
    (Redirect URI, permisos y consentimiento, lectura de grupos y, si hace falta, un secreto nuevo)."""
    check = session.get("entra_check")
    needs = entra_check.repairs(check["results"]) if check else None
    ecfg = settings()["auth"]["entra"]
    return _start_flow("repair", {"client_id": _existing_client_id(), "redirect_uri": redirect_uri(ecfg),
                                  "logout_url": frontchannel_logout_url(),
                                  "new_secret": bool(needs and needs["new_secret"]),
                                  "back": "wizard" if request.form.get("back") == "wizard" else "auth"})


@bp.route("/entra/grant-groups", methods=["POST"])
@admin_required
def entra_grant_groups():
    return _start_flow("grant_groups", {"client_id": _existing_client_id()})


@bp.route("/entra/register/cancel", methods=["POST"])
@admin_required
def entra_register_cancel():
    key, _flow = _register_flow()
    _drop_flow(key)
    return redirect(url_for("settings.entra_register_page"))


@bp.route("/entra/register/poll", methods=["POST"])
@admin_required
def entra_register_poll():
    """Comprueba si el administrador ya inició sesión; si es así, registra la aplicación.

    Con ``Accept: application/json`` (el JavaScript de la página) devuelve el estado; sin él (el
    botón «Ya he iniciado sesión») redirige.
    """
    wants_json = request.accept_mimetypes.best == "application/json"

    def answer(status: str, message: str = "", target: str | None = None, interval: int | None = None):
        if wants_json:
            if status == "complete" and message:
                flash(message, "info")  # el JavaScript va a ``target``: el resumen sale allí como aviso
            return jsonify(status=status, message=message, redirect=target, interval=interval)
        if message:
            flash(message, "info" if status in ("pending", "complete") else "error")
        return redirect(target or url_for("settings.entra_register_page"))

    key, flow = _register_flow()
    if not flow:
        return answer("expired", _("The sign-in code has expired or was cancelled. Start again."))
    try:
        body = entra_register.device_poll(flow["device_code"])
    except entra_register.RegisterError as exc:
        return answer("pending", str(exc), interval=flow["interval"])
    error = body.get("error", "")
    if error == "authorization_pending":
        return answer("pending", "" if wants_json else _("Microsoft has not confirmed the sign-in yet."),
                      interval=flow["interval"])
    if error == "slow_down":
        flow["interval"] = min(flow["interval"] + SLOW_DOWN_STEP, MAX_INTERVAL)
        return answer("pending", interval=flow["interval"])
    _drop_flow(key)  # un código canjeado (o rechazado) no se reutiliza
    if error:
        message = _("Microsoft refused the sign-in: %(error)s", error=entra_register._message(body) or error)
        audit_event("entra_app_register_failed", None, error)
        return answer("error", message)

    options, kind = flow["options"], flow.get("kind", "register")
    token = body["access_token"]
    if kind == "rotate":
        try:
            result = entra_register.rotate_secret(token, options["client_id"])
        except entra_register.RegisterError as exc:
            audit_event("entra_app_register_failed", options["client_id"], f"rotate:{exc}"[:200])
            return answer("error", _("The secret could not be renewed: %(error)s", error=exc))
        _draft, save_error = save_partial(lambda: {"auth": {"entra": {"client_secret": result["client_secret"],
                                                               "secret_expires": result["secret_expires"]}}},
                                         strict=True)
        if save_error:
            return answer("error", str(save_error))
        session.pop("entra_check", None)
        mark_new_secret()
        audit_event("entra_secret_rotated", options["client_id"], result["secret_expires"])
        return answer("complete", _("New client secret created and saved. The previous one keeps working until it "
                                    "expires."), url_for("settings.section", name="auth"))
    if kind == "repair":
        try:
            result = entra_register.repair_app(token, options["client_id"], redirect_uri=options["redirect_uri"],
                                               new_secret=options["new_secret"],
                                               logout_url=options.get("logout_url", ""))
        except entra_register.RegisterError as exc:
            audit_event("entra_app_register_failed", options["client_id"], f"repair:{exc}"[:200])
            return answer("error", _("The application could not be repaired: %(error)s", error=exc))
        if result.get("client_secret"):
            _draft, save_error = save_partial(lambda: {"auth": {"entra": {
                "client_secret": result["client_secret"], "secret_expires": result["secret_expires"]}}}, strict=True)
            if save_error:
                return answer("error", str(save_error))
            mark_new_secret()
        if result.get("signin_consent"):
            accounts.record_signin_scopes(get_db(), "entra", result["signin_consent"], source="consent")
        audit_event("entra_app_repaired", options["client_id"], "; ".join(result["fixed"])[:200] or "-")
        message = (_("Repaired: %(list)s.", list="; ".join(result["fixed"])) if result["fixed"]
                   else _("Nothing to repair: the application was already correct."))
        if result["warnings"]:
            message += " " + _("Could not repair: %(list)s.", list="; ".join(result["warnings"]))
        _run_check()  # el resultado, ya con lo arreglado (un secreto nuevo sale como «activándose»)
        target = url_for("settings.entra_setup", step=4) if options.get("back") == "wizard" \
            else url_for("settings.section", name="auth")
        return answer("complete", message, target)
    if kind == "grant_groups":
        try:
            entra_register.grant_group_read(token, options["client_id"])
        except entra_register.RegisterError as exc:
            audit_event("entra_app_register_failed", options["client_id"], f"groups:{exc}"[:200])
            return answer("error", _("Reading groups could not be granted: %(error)s", error=exc))
        session.pop("entra_check", None)
        audit_event("entra_groups_granted", options["client_id"])
        return answer("complete", _("The application can now read group names (it may take a minute)."),
                      url_for("settings.section", name="auth"))

    try:
        result = entra_register.register_app(token, **options)
    except entra_register.RegisterError as exc:
        audit_event("entra_app_register_failed", None, str(exc)[:200])
        return answer("error", _("The application could not be registered: %(error)s", error=exc))
    except Exception as exc:  # noqa: BLE001 — nunca un 500 a mitad del registro: que se vea qué pasó
        current_app.logger.exception("Entra ID registration failed")
        audit_event("entra_app_register_failed", None, repr(exc)[:200])
        return answer("error", _("The application could not be registered: %(error)s", error=exc))

    def _entra_fields():
        mappings = dict(settings()["auth"]["entra"]["role_mappings"])
        if result["app_roles"]:
            mappings[entra_register.ADMIN_ROLE.lower()] = "admin"
        # La dirección de vuelta no se guarda: se calcula siempre de la dirección pública
        return {"auth": {"entra": {"tenant_id": result["tenant_id"], "client_id": result["client_id"],
                                   "client_secret": result["client_secret"], "secret_expires": result["secret_expires"],
                                   "role_mappings": mappings}}}
    _draft, save_error = save_partial(_entra_fields, strict=True)
    if save_error:
        return answer("error", _("The application was created in Entra ID (%(client)s) but the settings could not "
                                 "be saved: %(error)s", client=result["client_id"], error=save_error))
    mark_new_secret()
    if result.get("signin_consent"):
        accounts.record_signin_scopes(get_db(), "entra", result["signin_consent"], source="consent")
    audit_event("entra_app_registered", result["client_id"], result["tenant_id"])
    session["entra_registered"] = {"client_id": result["client_id"], "portal_url": result["portal_url"],
                                   "secret_expires": result["secret_expires"], "warnings": result["warnings"]}
    return answer("complete", _("Application registered in Entra ID and saved."),
                  url_for("settings.entra_setup", step=4))


search.action("key", _l("Renew the Entra ID secret"), "settings.section", {"name": "auth"},
              "f-auth-entra-secret_expires", "secreto entra renovar rotar microsoft secret rotate", order=60)
search.action("globe", _l("Register the application in Entra ID"), "settings.entra_register_page",
              words="entra registrar app microsoft", order=70)

"""Conectar una aplicación iniciando sesión en el navegador (core/connect.py: el flujo y su seguridad).

- ``/connect/<cliente>``: con la sesión del usuario (si no la hay, pasa por el inicio de sesión, también
  el de Entra ID, y vuelve), pregunta si se permite y, al aceptar, devuelve el navegador a la aplicación
  con un código de un solo uso.
- ``/connect/token``: la aplicación canjea el código con su verifier y recibe el token (JSON). Sin cookies
  (no hay CSRF posible: el secreto es el verifier).
- ``/connect/desktop``: entrar sin navegador con la cuenta del sistema (VS Code con la cuenta de Windows). ``GET``
  dice qué métodos lo admiten y qué token pedir a su proveedor (``AuthMethod.desktop``); ``POST`` canjea ese token
  (``AuthMethod.desktop_identity``: comprobado de verdad, con su firma) por un token de API, con las mismas reglas
  que el inicio de sesión de ese método (``accounts.login_sso``: alta automática, grupos permitidos, roles…).
"""
from __future__ import annotations

from flask import Blueprint, abort, g, jsonify, render_template, request

from ... import providers
from ...core import accounts, connect, ipban, tokens
from ...providers import AuthDenied
from ...db.repositories import audit
from ..context import get_db, settings
from ...i18n import _
from ..guards import audit_event, client_ip, login_required, require_api_tokens
from .auth import rename_in_shares

bp = Blueprint("connect", __name__)


@bp.route("/connect/token", methods=["POST"])
def token():
    if not settings()["security"]["api_tokens"]:
        return jsonify(error="tokens_disabled"), 403
    data = request.get_json(silent=True) or request.form
    try:
        user, plain, name, days = connect.redeem(get_db(), data.get("code"), data.get("verifier"),
                                                 max_days=settings()["security"]["api_token_max_days"])
    except connect.ConnectError:
        ipban.offense(get_db(), settings(), client_ip(), "bad_token")
        return jsonify(error="invalid_grant"), 400
    audit.log(get_db(), "api_token_created", name, username=user["username"], ip=client_ip(), detail="connect")
    response = jsonify(username=user["username"], token=plain, name=name, days=days)
    response.headers["Cache-Control"] = "no-store"
    return response


# Lo que cuenta para el bloqueo de IPs: un token que no firmó Microsoft (la firma se mira lo primero). Un token
# auténtico caducado, de otra organización o de otra aplicación es un error de quien lo usa, no un ataque (como los
# tokens de API caducados, que tampoco cuentan: la IP de una oficina entera)
BAD_TOKEN = frozenset({"invalid_token"})
# Lo que se dice a la aplicación de cada rechazo de un token auténtico
REFUSED = frozenset({"expired", "client", "tenant", "version"})


def _desktop_methods() -> list:
    cfg = settings()
    return [(m, found) for m in providers.methods() if m.enabled(cfg) and (found := m.desktop(m.section(cfg)))]


@bp.route("/connect/desktop", methods=["GET", "POST"])
def desktop():
    """``GET``: los métodos con los que una aplicación de escritorio puede entrar con la cuenta del sistema y qué
    pedir a su proveedor (nada secreto: el tenant y el permiso ya se ven en el inicio de sesión web). ``POST`` (JSON
    ``method``, ``client``, ``access_token``, ``device``): el token de API, como ``/connect/token``."""
    if request.method == "GET":
        return jsonify(methods=[{"key": m.key, "label": str(m.label), **found} for m, found in _desktop_methods()])
    cfg = settings()
    if not cfg["security"]["api_tokens"]:
        return jsonify(error="tokens_disabled", message=_("API tokens are disabled.")), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    method = next((m for m, _found in _desktop_methods() if m.key == data.get("method")), None)
    if method is None:
        return jsonify(error="not_enabled", message=_("Signing in from desktop applications is not enabled.")), 404
    if not isinstance(data.get("client"), str) or data["client"] not in connect.CLIENTS:
        return jsonify(error="unknown_client", message=_("Unknown application.")), 400
    ip = client_ip()
    try:
        identity = method.desktop_identity(method.section(cfg), str(data.get("access_token") or ""))
    except AuthDenied as exc:
        if exc.code == "unavailable":
            # Microsoft no contesta: no es culpa de quien entra, y sin auditar (cualquiera, sin autenticar, llenaría
            # la auditoría mientras dure; el registro del servidor ya lo dice al pedir las claves)
            return jsonify(error="unavailable", message=exc.message), 503
        if exc.code in BAD_TOKEN:
            ipban.offense(get_db(), cfg, ip, "bad_token")
        audit.log(get_db(), "login_failed", ip=ip, detail=f"{method.key}:desktop:{exc.code}")
        invalid = exc.code in BAD_TOKEN or exc.code in REFUSED
        return jsonify(error="invalid_token" if invalid else "denied", message=exc.message), 401 if invalid else 403
    try:
        # Sin reactivar una cuenta que desactivó el directorio: el token de Microsoft puede ser de antes (vale ~1 h)
        user = accounts.login_sso(get_db(), cfg, method.key, identity, ip=ip, on_rename=rename_in_shares,
                                  reenable=False)
    except accounts.AccountError as exc:
        audit.log(get_db(), "login_denied", username=identity.username, ip=ip,
                  detail=f"{method.key}:desktop:{exc.code}")
        return jsonify(error="denied", message=exc.message), 403
    plain, name, days = connect.desktop_token(get_db(), user, data["client"], str(data.get("device") or ""),
                                              max_days=cfg["security"]["api_token_max_days"])
    label = connect.CLIENTS[data["client"]].label
    audit.log(get_db(), "app_authorized", label, username=user["username"], ip=ip, detail=f"{method.key}:desktop")
    audit.log(get_db(), "api_token_created", name, username=user["username"], ip=ip, detail="connect-desktop")
    response = jsonify(username=user["username"], token=plain, name=name, days=days)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/connect/<client>", methods=["GET", "POST"])
@login_required
def authorize(client: str):
    require_api_tokens()
    values = request.values
    redirect_uri, state = values.get("redirect_uri", ""), values.get("state", "")
    try:
        app = connect.check_request(client, redirect_uri, values.get("challenge"), state)
    except connect.ConnectError as exc:
        abort(400, description=str(exc))
    device = connect.clean_device(values.get("device"))
    if request.method == "POST":
        if request.form.get("action") != "allow":
            return render_template("connect.html", app=app, done="denied",
                                   target=connect.back_url(redirect_uri, error="access_denied", state=state))
        try:
            scope = request.form.get("scope", "write")
            max_days = settings()["security"]["api_token_max_days"]
            days = tokens.clamp_days(int(request.form.get("days", "365")), max_days)
            code = connect.issue(g.user["id"], app, device, values["challenge"], scope=scope, days=days,
                                 max_days=max_days)
        except (ValueError, connect.ConnectError) as exc:
            abort(400, description=str(exc))
        audit_event("app_authorized", app.label, detail=device or None)
        return render_template("connect.html", app=app, done="allowed",
                               target=connect.back_url(redirect_uri, code=code, state=state))
    return render_template("connect.html", app=app, done=None, device=device, client=client,
                           redirect_uri=redirect_uri, state=state, challenge=values.get("challenge"),
                           SCOPE_LABELS=tokens.SCOPE_LABELS,
                           EXPIRY_DAYS=tokens.allowed_days(settings()["security"]["api_token_max_days"]))

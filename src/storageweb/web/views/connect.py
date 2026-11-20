"""Conectar una aplicación iniciando sesión en el navegador (core/connect.py: el flujo y su seguridad).

- ``/connect/<cliente>``: con la sesión del usuario (si no la hay, pasa por el inicio de sesión, también
  el de Entra ID, y vuelve), pregunta si se permite y, al aceptar, devuelve el navegador a la aplicación
  con un código de un solo uso.
- ``/connect/token``: la aplicación canjea el código con su verifier y recibe el token (JSON). Sin cookies
  (no hay CSRF posible: el secreto es el verifier).
"""
from __future__ import annotations

from flask import Blueprint, abort, g, jsonify, render_template, request

from ...core import connect, ipban, tokens
from ...db.repositories import audit
from ...i18n import _
from ..context import get_db, settings
from ..guards import audit_event, client_ip, login_required

bp = Blueprint("connect", __name__)


def _tokens_enabled() -> None:
    if not settings()["security"]["api_tokens"]:
        abort(403, description=_("API tokens are disabled."))


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


@bp.route("/connect/<client>", methods=["GET", "POST"])
@login_required
def authorize(client: str):
    _tokens_enabled()
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

"""Sesiones y tokens de API de cualquier usuario (Personas → Sesiones y tokens, y la ficha del usuario)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import abort, flash, g, redirect, request, url_for

from ....db.repositories import users
from ....db.repositories import sessions as session_repo
from ....i18n import _, _l, ngettext
from ....db.repositories import api_tokens as token_repo
from ...context import get_db
from ...guards import admin_required, audit_event
from ... import search
from . import bp
from .common import back


# --------------------------------------------------------------------------- sesiones

@bp.route("/sessions/close-all", methods=["POST"])
@admin_required
def sessions_close_all():
    """Cierra todas las sesiones salvo la del admin que lo pide."""
    closed = 0
    for row in session_repo.list_all(get_db()):
        if row["id"] != g.get("session_id"):
            session_repo.delete(get_db(), row["id"])
            closed += 1
    audit_event("sessions_closed", "*", str(closed))
    flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    return redirect(url_for("settings.section", name="sessions"))


IDLE_CHOICES = (1, 24, 24 * 7, 24 * 30)  # horas


@bp.route("/sessions/close-selected", methods=["POST"])
@admin_required
def sessions_close_selected():
    """Cierra las sesiones marcadas en la lista (nunca la del admin que lo pide)."""
    closed = 0
    for sid in set(request.form.getlist("sids")):
        if sid != g.get("session_id") and session_repo.get(get_db(), sid) is not None:
            session_repo.delete(get_db(), sid)
            closed += 1
    if closed:
        audit_event("sessions_closed", "selected", str(closed))
        flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    else:
        flash(_("Select at least one session."), "error")
    return redirect(url_for("settings.section", name="sessions"))


@bp.route("/sessions/close-idle", methods=["POST"])
@admin_required
def sessions_close_idle():
    """Cierra las sesiones sin actividad desde hace más de las horas elegidas."""
    hours = request.form.get("hours", type=int)
    if hours not in IDLE_CHOICES:
        abort(400)
    before = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    closed = 0
    for row in session_repo.list_all(get_db()):
        if row["id"] != g.get("session_id") and row["last_seen"] < before:
            session_repo.delete(get_db(), row["id"])
            closed += 1
    audit_event("sessions_closed", f"idle>{hours}h", str(closed))
    flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    return redirect(url_for("settings.section", name="sessions"))


@bp.route("/sessions/<sid>/close", methods=["POST"])
@admin_required
def session_close(sid: str):
    row = session_repo.get(get_db(), sid)
    if row is not None:
        session_repo.delete(get_db(), sid)
        user = users.get_by_id(get_db(), row["user_id"])
        audit_event("session_closed", user["username"] if user else None, row["ip"])
        flash(_("Session closed."), "info")
    return back(url_for("settings.section", name="sessions"))


@bp.route("/sessions/user/<int:user_id>/close", methods=["POST"])
@admin_required
def user_sessions_close(user_id: int):
    user = users.get_by_id(get_db(), user_id)
    if user is None:
        abort(404)
    keep = g.get("session_id") if user_id == g.user["id"] else None
    closed = session_repo.delete_for_user(get_db(), user_id, keep=keep)
    audit_event("sessions_closed", user["username"], str(closed))
    flash(ngettext("%(num)s session closed.", "%(num)s sessions closed.", closed), "info")
    return back(url_for("admin.user_edit", user_id=user_id))


@bp.route("/sessions/user/<int:user_id>/tokens/<int:token_id>/delete", methods=["POST"])
@admin_required
def user_token_delete(user_id: int, token_id: int):
    token = token_repo.get(get_db(), token_id)
    user = users.get_by_id(get_db(), user_id)
    if token is None or user is None or token["user_id"] != user_id:
        abort(404)
    token_repo.delete(get_db(), token_id)
    audit_event("api_token_revoked", user["username"], token["name"])
    flash(_("Token «%(name)s» revoked.", name=token["name"]), "info")
    return back(url_for("admin.user_edit", user_id=user_id))


search.action("logout", _l("Close all sessions"), "settings.section", {"name": "sessions"},
              words="sesiones cerrar todas logout", order=80)

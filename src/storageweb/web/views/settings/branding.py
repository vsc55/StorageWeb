"""Logo propio (Sistema → General y marca)."""
from __future__ import annotations

from flask import flash, redirect, request, url_for

from ....core import branding
from ....i18n import _
from ...context import boot_config
from ...guards import admin_required, audit_event
from . import bp
from .common import save_partial


# --------------------------------------------------------------------------- marca

@bp.route("/branding/logo", methods=["POST"])
@admin_required
def branding_logo():
    item = request.files.get("logo")
    cfg = boot_config()
    try:
        if not item or not item.filename:
            raise branding.BrandingError(_("Choose an image."))
        name = branding.save_logo(cfg, item.filename, item.read(branding.MAX_BYTES + 1))
    except branding.BrandingError as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.section", name="general"))
    _draft, error = save_partial(lambda: {"branding": {"logo": name}}, strict=True)
    if error:
        flash(str(error), "error")
    else:
        audit_event("branding_logo_updated", None, name)
        flash(_("Logo updated."), "info")
    return redirect(url_for("settings.section", name="general"))


@bp.route("/branding/logo/delete", methods=["POST"])
@admin_required
def branding_logo_delete():
    branding.remove_logo(boot_config())
    save_partial(lambda: {"branding": {"logo": ""}}, strict=True)
    audit_event("branding_logo_removed")
    flash(_("Logo removed."), "info")
    return redirect(url_for("settings.section", name="general"))

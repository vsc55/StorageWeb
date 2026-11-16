"""Logo e imagen del inicio de sesión propios (Sistema → General y marca)."""
from __future__ import annotations

from flask import flash, redirect, request, url_for

from ....core import branding
from ....i18n import _
from ...context import boot_config
from ...guards import admin_required, audit_event
from . import bp
from .common import save_partial

# Imagen → (campo del formulario, acciones de auditoría al subir y al quitar, mensajes de subida y de borrado)
_IMAGES = {
    "logo": ("logo", "branding_logo_updated", "branding_logo_removed",
             lambda: _("Logo updated."), lambda: _("Logo removed.")),
    "login_image": ("login_image", "branding_login_image_updated", "branding_login_image_removed",
                    lambda: _("Sign-in image updated."), lambda: _("Sign-in image removed.")),
}


def _back():
    return redirect(url_for("settings.section", name="general"))


def _upload(kind: str):
    field, updated, _removed, done, _gone = _IMAGES[kind]
    item = request.files.get(field)
    cfg = boot_config()
    try:
        if not item or not item.filename:
            raise branding.BrandingError(_("Choose an image."))
        name = branding.save_image(cfg, kind, item.filename, item.read(branding.IMAGES[kind].max_bytes + 1))
    except branding.BrandingError as exc:
        flash(str(exc), "error")
        return _back()
    _draft, error = save_partial(lambda: {"branding": {kind: name}}, strict=True)
    if error:
        flash(str(error), "error")
    else:
        audit_event(updated, None, name)
        flash(done(), "info")
    return _back()


def _remove(kind: str):
    _field, _updated, removed, _done, gone = _IMAGES[kind]
    branding.remove_image(boot_config(), kind)
    save_partial(lambda: {"branding": {kind: ""}}, strict=True)
    audit_event(removed)
    flash(gone(), "info")
    return _back()


@bp.route("/branding/logo", methods=["POST"])
@admin_required
def branding_logo():
    return _upload("logo")


@bp.route("/branding/logo/delete", methods=["POST"])
@admin_required
def branding_logo_delete():
    return _remove("logo")


@bp.route("/branding/login-image", methods=["POST"])
@admin_required
def branding_login_image():
    return _upload("login_image")


@bp.route("/branding/login-image/delete", methods=["POST"])
@admin_required
def branding_login_image_delete():
    return _remove("login_image")

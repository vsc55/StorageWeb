"""Seguridad → Contraseñas: la lista de contraseñas comunes (descargarla de las direcciones guardadas, subir una o
volver a la de serie). Las reglas se guardan con el formulario de la página (``forms._passwords``); la lista la
lleva ``core/passwords``. Y el probador: qué reglas cumple una contraseña escrita, sin guardar nada."""
from __future__ import annotations

import copy

from flask import flash, jsonify, request

from ....core import passwords
from ....i18n import _, ngettext
from ....providers import local
from ....settings import ConfigError, loader
from ...context import boot_config, runtime, settings
from ...forms import uploaded
from ...guards import admin_required, audit_event
from . import bp, forms
from .common import to_section


@bp.route("/passwords/list/download", methods=["POST"])
@admin_required
def password_list_download():
    urls = settings()["security"]["password_list_urls"]
    try:
        count = passwords.download(boot_config()["data_dir"], urls)
    except passwords.PasswordListError as exc:
        flash(exc.message, "error")
        return to_section("passwords")
    audit_event("password_list_updated", None, "download")
    flash(_("Common passwords list updated: %(num)s passwords.", num=count), "info")
    return to_section("passwords")


@bp.route("/passwords/list/upload", methods=["POST"])
@admin_required
def password_list_upload():
    file = uploaded("file")
    if file is None:
        flash(_("Choose a text file with one password per line."), "error")
        return to_section("passwords")
    try:
        count = passwords.upload(boot_config()["data_dir"], file.read(passwords.MAX_BYTES + 1), file.filename)
    except passwords.PasswordListError as exc:
        flash(exc.message, "error")
        return to_section("passwords")
    audit_event("password_list_updated", None, "upload")
    flash(_("Common passwords list updated: %(num)s passwords.", num=count), "info")
    return to_section("passwords")


@bp.route("/passwords/list/reset", methods=["POST"])
@admin_required
def password_list_reset():
    if passwords.reset(boot_config()["data_dir"]):
        audit_event("password_list_reset")
        flash(_("The list that comes with StorageWeb is used again."), "info")
    return to_section("passwords")


def _page_rules() -> dict:
    """Las reglas que hay en la página ahora (el formulario va con la petición), aunque no estén guardadas: así se
    prueba lo que se está cambiando. Los campos bloqueados (config.json/entorno) se quedan con su valor; sin el
    formulario, las guardadas. Validadas como al guardar (:class:`ConfigError` si algo no vale)."""
    sec = copy.deepcopy(settings()["security"])
    if request.form.get("from_page") == "1":
        for key, value in forms._passwords()["security"].items():
            if not runtime().lock_of(f"security.{key}"):
                sec[key] = value
        loader.password_settings(sec)
    return local.rules({"security": sec, "data_dir": settings().get("data_dir")})


@bp.route("/passwords/test", methods=["POST"])
@admin_required
def password_test():
    """El probador de la página: cada regla, con lo que hay en la página, para la contraseña escrita (y un nombre de
    usuario, si se da). POST con el token CSRF (en la cabecera ``X-CSRF-Token``); no guarda nada ni la escribe en
    ningún sitio."""
    password = request.form.get("test_password", "")[:local.MAX_PASSWORD_LENGTH * 8]
    username = request.form.get("test_username", "").strip()[:200]
    try:
        rules = _page_rules()
    except ConfigError as exc:
        return jsonify({"ok": False, "checks": [], "summary": str(exc)})
    live = request.form.get("live") == "1"      # mientras se escribe: sin preguntar a internet en cada tecla
    results = list(local.checks(password, username=username, **{**rules, "breach_check": rules["breach_check"]
                                                                  and not live}))
    if live and rules["breach_check"]:
        results.append({"key": "breach", "label": _("Does not appear in known data breaches"), "ok": None,
                        "message": _("Press «Try» to check it.")})
    failed = [r for r in results if r["ok"] is False]
    return jsonify({**local.verdict(password, results), "checks": results,
                    "summary": _("It would be accepted.") if not failed else
                    ngettext("It would be rejected: %(num)s rule is not met.",
                             "It would be rejected: %(num)s rules are not met.", len(failed))})


@bp.route("/passwords/generate", methods=["POST"])
@admin_required
def password_generate():
    """El botón «Generar» del probador: una aleatoria que cumple las reglas que hay en la página (guardadas o no)."""
    try:
        rules = _page_rules()
        password = local.generate(username=request.form.get("test_username", "").strip()[:200], **rules)
    except (ConfigError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(password=password)

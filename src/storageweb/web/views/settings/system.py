"""*Sistema → Información*: versión, proceso, máquina, base de datos, carpetas y componentes (``core/diagnostics``), y
el mismo contenido como informe para adjuntar a una incidencia (texto o JSON)."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from flask import current_app, flash, g, jsonify, request
from ...downloads import attachment

from ....core import advisories, backends, diagnostics, maintenance
from ....i18n import _
from ....settings import fields
from ...context import boot_config, get_db, network_diagnosis, settings
from ...guards import admin_required, audit_event, client_ip, wants_json
from . import bp
from .common import to_section
from ....clock import now_iso

FORMATS = {"txt": ("text/plain; charset=utf-8", "txt"), "json": ("application/json", "json")}


def _folders(boot: dict, cfg: dict) -> list[dict]:
    """Las carpetas donde escribe StorageWeb en este servidor. Las que se crean al hacer falta, ``on_demand``."""
    data_dir = boot["data_dir"]
    rows = [{"key": "data", "path": data_dir},
            {"key": "backups", "path": str(maintenance.backup_dir(boot)), "on_demand": True},
            {"key": "uploads", "path": str(backends.staging_dir(boot)), "on_demand": True},
            {"key": "logs", "path": str(backends.staging_dir(boot).parent / "logs"), "on_demand": True}]
    if not cfg["storage"].get("home_location"):         # en una ubicación remota no hay carpeta en este disco
        rows.insert(1, {"key": "homes", "path": diagnostics.home_base(cfg["storage"]["home_template"]),
                        "on_demand": True})
    return diagnostics.folders(rows)


def collect() -> dict:
    """Todo lo de la página, de una vez (la página y el informe son lo mismo)."""
    boot, cfg = boot_config(), settings()
    net = network_diagnosis(cfg)
    return {
        "generated": now_iso(),
        "system": diagnostics.system(debug=current_app.debug, threads=boot["server"]["threads"]),
        "database": diagnostics.database(get_db(), boot["database"]),
        "folders": _folders(boot, cfg),
        "components": diagnostics.components(),
        # Las bibliotecas de JavaScript copiadas (Mermaid, highlight.js), con el nombre del ajuste que las usa
        "javascript": [{**lib, "feature": str(fields.label(lib["setting"])) if lib["setting"] else ""}
                       for lib in diagnostics.vendored(Path(current_app.static_folder) / "vendor")],
        "network": {"scheme": net["seen"]["scheme"], "host": net["seen"]["host"], "client": net["seen"]["client"],
                    "public_url": cfg["network"].get("public_url", ""),
                    "behind_proxy": boot["server"]["behind_proxy"],
                    "problems": [text for level, text in net["notes"] if level in ("warn", "danger")]},
    }


def context() -> dict:
    return {"diag": collect()}


@bp.route("/system/advisories", methods=["POST"])
@admin_required
def system_advisories():
    """Empieza a preguntar a PyPI, npm y OSV.dev por lo instalado (versiones nuevas y vulnerabilidades), en segundo
    plano (``core.advisories.run_job``). Si ya hay una en marcha (otra pestaña, otro administrador o la automática),
    no empieza otra. El navegador sigue el avance con :func:`system_advisories_status`; sin JavaScript, se vuelve a la
    página."""
    as_json = wants_json()
    rows = advisories.default_rows(Path(current_app.static_folder) / "vendor")
    if not advisories.try_start(g.user["username"], len(rows)):
        if as_json:
            return jsonify(advisories.job_status()), 409
        flash(_("A check is already running."), "info")
        return to_section("vulnerabilities", "advisories")
    args = (rows, boot_config()["database"], g.user["username"], client_ip())
    # En los tests, de una vez (nada queda corriendo entre un test y otro), salvo que el test pida el hilo
    if current_app.config.get("SW_SYNC_JOBS", current_app.testing):
        advisories.run_job(*args)
    else:
        threading.Thread(target=advisories.run_job, args=args, name="storageweb-advisories", daemon=True).start()
    if as_json:
        return jsonify(advisories.job_status()), 202
    flash(_("Checking the libraries in the background: the result will be here when it finishes."), "info")
    return to_section("vulnerabilities", "advisories")


@bp.route("/system/advisories/status")
@admin_required
def system_advisories_status():
    """Cómo va la comprobación en marcha (la barra de progreso), o cómo acabó la última."""
    return jsonify(advisories.job_status())


@bp.route("/system/report")
@admin_required
def system_report():
    """El informe para adjuntar a una incidencia: lo mismo que enseña la página, en texto o JSON. Sin secretos."""
    fmt = request.args.get("format", "txt")
    mimetype, ext = FORMATS.get(fmt, FORMATS["txt"])
    data = collect()
    body = json.dumps(data, indent=2, ensure_ascii=False) if ext == "json" else diagnostics.as_text(data)
    audit_event("system_report", None, ext)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return attachment(body, mimetype, f"storageweb-informe-{stamp}.{ext}")

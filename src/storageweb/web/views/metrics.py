"""``/metrics``: métricas para Prometheus (``metrics.enabled``).

Acceso con el token (``Authorization: Bearer <metrics.token>``), desde las redes de ``metrics.allowed_networks``
o, si no hay ninguno de los dos, solo desde el propio servidor. Desactivadas responde 404 (como si no existiera).
No usa la sesión ni los tokens de API (``guards.load_current_user`` se salta esta ruta). También cuenta aquí
cada petición (``storageweb_http_requests_total`` y el tiempo de respuesta por ruta).
"""
from __future__ import annotations

import time

from flask import Blueprint, Response, abort, g, request

from ... import metrics
from ...core import ipban, monitoring
from ..context import boot_config, get_db, settings
from ..guards import client_ip

bp = Blueprint("metrics", __name__)
ENDPOINT = "metrics.metrics_page"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@bp.route("/metrics")
def metrics_page():
    cfg = settings()
    if not monitoring.enabled(cfg):
        abort(404)
    header = request.headers.get("Authorization", "")
    bearer = header[7:].strip() if header[:7].lower() == "bearer " else None
    if not monitoring.allowed(cfg, client_ip(), bearer):
        if bearer:  # un token equivocado cuenta para el bloqueo de IPs, como los de la API
            ipban.offense(get_db(), cfg, client_ip(), "bad_token")
        return Response("403 Forbidden\n", 403, mimetype="text/plain")
    body = monitoring.render(get_db(), cfg, {**boot_config(), "maintenance": cfg["maintenance"]})
    return Response(body, 200, headers={"Content-Type": CONTENT_TYPE, "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- recuento de peticiones

def start_timer() -> None:
    g.sw_started = time.perf_counter()


def count_request(response):
    started = g.pop("sw_started", None)
    endpoint = request.endpoint or "unknown"
    metrics.inc("storageweb_http_requests_total", endpoint=endpoint, method=request.method,
                code=response.status_code)
    if started is not None:
        metrics.inc("storageweb_http_request_duration_seconds_sum", time.perf_counter() - started, endpoint=endpoint)
        metrics.inc("storageweb_http_request_duration_seconds_count", endpoint=endpoint)
    return response

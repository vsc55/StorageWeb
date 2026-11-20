"""Métricas para Prometheus: contadores en memoria y el formato de texto (0.0.4), sin dependencias.

Cualquier capa puede contar algo con :func:`inc` (peticiones, eventos de la auditoría, bytes subidos y
descargados…); los valores que se calculan al leer (usuarios, espacio, ubicaciones…) los añade
``core.monitoring``. Los contadores son del proceso: empiezan en 0 al arrancar, como espera Prometheus.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

START_TIME = time.time()

# Nombre → (tipo, ayuda) de los contadores que se van sumando
COUNTERS = {
    "storageweb_http_requests_total": "HTTP requests by endpoint, method and status code.",
    "storageweb_http_request_duration_seconds_sum": "Total time spent answering requests, by endpoint.",
    "storageweb_http_request_duration_seconds_count": "Requests answered, by endpoint (with the _sum: average time).",
    "storageweb_events_total": "Audit events by action (logins, failed logins, uploads, downloads, deletions…).",
    "storageweb_upload_bytes_total": "Bytes uploaded, by way (web, api, webdav).",
    "storageweb_download_bytes_total": "Bytes downloaded, by way (web, webdav).",
    "storageweb_quota_rejections_total": "Writes rejected because they did not fit in the quota.",
    "storageweb_audit_forward_errors_total": "Audit events that could not be forwarded to syslog or the file.",
    "storageweb_audit_forward_dropped_total": "Audit events not forwarded because the queue was full.",
}

_lock = threading.Lock()
_values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def inc(name: str, value: float = 1, **labels) -> None:
    """Suma ``value`` al contador ``name`` con esas etiquetas. Nunca falla (las métricas no rompen nada)."""
    if not value:
        return
    key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
    with _lock:
        _values[key] = _values.get(key, 0) + value


def clear() -> None:
    with _lock:
        _values.clear()


@dataclass
class Family:
    """Una métrica calculada al leer: ``samples`` = [(etiquetas, valor)]."""
    name: str
    kind: str          # gauge | counter
    help: str
    samples: list[tuple[dict, float]] = field(default_factory=list)


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "NaN" if math.isnan(value) else ("+Inf" if value > 0 else "-Inf")
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _line(name: str, labels, value: float) -> str:
    items = labels.items() if isinstance(labels, dict) else labels
    text = ",".join(f'{k}="{_escape(v)}"' for k, v in items)
    return f"{name}{{{text}}} {_number(value)}" if text else f"{name} {_number(value)}"


def counters() -> list[Family]:
    """Los contadores sumados hasta ahora, como familias (los ``_sum``/``_count`` van con su resumen)."""
    with _lock:
        snapshot = dict(_values)
    families: dict[str, Family] = {}
    for (name, labels), value in sorted(snapshot.items()):
        family = families.setdefault(name, Family(name, "counter", COUNTERS.get(name, name)))
        family.samples.append((dict(labels), value))
    return list(families.values())


def render(families: Iterable[Family]) -> str:
    """Formato de exposición de texto de Prometheus."""
    out: list[str] = []
    for family in families:
        base = family.name
        if base.endswith(("_sum", "_count")) and family.kind == "counter":
            # Las dos mitades de un resumen comparten nombre base y tipo «summary»
            stem = base.rsplit("_", 1)[0]
            if not any(line.startswith(f"# TYPE {stem} ") for line in out):
                out.append(f"# HELP {stem} {_escape(family.help)}")
                out.append(f"# TYPE {stem} summary")
        else:
            out.append(f"# HELP {base} {_escape(family.help)}")
            out.append(f"# TYPE {base} {family.kind}")
        out.extend(_line(base, labels, value) for labels, value in family.samples)
    return "\n".join(out) + "\n"

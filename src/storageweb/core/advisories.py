"""Qué dice el mundo de las versiones instaladas: si hay una más nueva y si la instalada tiene vulnerabilidades
conocidas (CVE, avisos de GitHub, PYSEC). Basado en el de ServiceSentry (mismo autor).

Lo único de *Sistema → Información* que sale a internet, así que:

* **Nunca lo hace sin que se pida.** Ni al arrancar ni al abrir la página: un servidor en una red aislada que llama
  a pypi.org porque alguien abrió una página es un fallo. Se hace al pulsar un botón o cada
  ``security.dependency_check_hours`` horas (la tarea ``dependency_check``; de serie 24, 0 = nunca sola); las dos
  cosas se auditan.
* **No puede costar nada.** Tiempos de espera cortos, pocas conexiones a la vez, y todo fallo es una frase en la
  página, nunca una excepción; también los parciales: un paquete que PyPI no contesta es una celda desconocida.
* **La lista la hace el servidor** (lo instalado y las bibliotecas de JavaScript copiadas), nunca la petición: si el
  navegador pudiera nombrar los paquetes, StorageWeb preguntaría a un servicio externo lo que otro quisiera.

**Dos fuentes.** OSV.dev contesta las vulnerabilidades de todo en UNA petición (y luego una por aviso distinto, para
saber lo grave que es); la versión más nueva es una petición pequeña por paquete a PyPI o a npm, en un grupo
pequeño. Por eso la mitad de las vulnerabilidades sigue funcionando donde pypi.org está bloqueado.

Las gravedades no son opinión de StorageWeb: la publicada por la base de datos o, si solo hay un vector CVSS 3.x, la
puntuación base que define su especificación.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import __version__
from ..db import connect
from ..db.repositories import audit
from ..i18n import _, ngettext
from . import diagnostics, maintenance
from .alerts import alert, source
from .diagnostics import KINDS
from ..clock import now_iso

_log = logging.getLogger(__name__)
# Las bibliotecas de JavaScript copiadas (tools/vendor.py): una ruta del paquete, no un import de la capa web
VENDOR_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "vendor"

# Solo por HTTPS: estas respuestas deciden qué se actualiza, y una petición degradada la contesta otro
PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}/latest"
OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_API = "https://api.osv.dev/v1/vulns/{vid}"
OSV_VULN_URL = "https://osv.dev/vulnerability/{vid}"
PROJECT_URLS = {"PyPI": "https://pypi.org/project/{name}/{version}/",
                "npm": "https://www.npmjs.com/package/{name}/v/{version}"}
ECOSYSTEMS = ("PyPI", "npm")

TIMEOUT = 6.0
# El documento de PyPI de un proyecto lleva TODAS sus versiones y ficheros: el de cryptography pasa de 3 MB
MAX_BODY = 16 << 20
WORKERS = 8           # pocas conexiones a la vez: un proxy de empresa no tiene por qué ver un abanico
MAX_DETAILS = 60      # avisos distintos de los que se pide el detalle (más, y la columna no es lo primero)
STATE_KEY = "advisories"     # en maintenance_state: la última comprobación, para la página y el Resumen

_NAME_RE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
_NUM_RE = re.compile(r"\d+")


def _headers() -> dict:
    # Un servicio que limita por cliente quiere saber quién pregunta: la petición anónima es la primera que frena
    return {"Accept": "application/json", "User-Agent": f"StorageWeb/{__version__} (diagnostics)"}


def _get_json(url: str, timeout: float, data: bytes | None = None) -> dict:
    """GET (o POST con ``data``) a una URL fija de arriba; ``{"ok": False, "error": …}`` en vez de lanzar."""
    headers = {**_headers(), **({"Content-Type": "application/json"} if data is not None else {})}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (solo https, URLs fijas)
            # Un byte más que el límite: llegar a él se DETECTA en vez de leer un documento cortado
            body = resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "not_found" if exc.code == 404 else "http", "status": int(exc.code)}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": "unreachable", "detail": str(exc)[:200]}
    if len(body) > MAX_BODY:
        return {"ok": False, "error": "too_large"}
    try:
        return {"ok": True, "data": json.loads(body.decode("utf-8", errors="replace"))}
    except ValueError:
        return {"ok": False, "error": "not_json"}


def project_url(ecosystem: str, name: str, version: str) -> str:
    """La página de esa versión en PyPI o npm. Se compone aquí: nunca un enlace que venga en la respuesta."""
    template = PROJECT_URLS.get(ecosystem)
    return template.format(name=name, version=version) if template and name and version else ""


def advisory_url(vid: str) -> str:
    """Dónde se lee un aviso (osv.dev), o ``""`` si el identificador no lo parece."""
    return OSV_VULN_URL.format(vid=vid) if _ID_RE.match(str(vid or "")) else ""


# --------------------------------------------------------------------------- gravedad (CVSS 3.x)

_CVSS_W = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
# Los privilegios dependen del alcance: con el alcance cambiado valían más
_CVSS_PR = {False: {"N": 0.85, "L": 0.62, "H": 0.27}, True: {"N": 0.85, "L": 0.68, "H": 0.50}}
RATINGS = ("none", "low", "moderate", "high", "critical")


def _roundup(value: float) -> float:
    """Un decimal, siempre hacia arriba: el redondeo de la especificación, sobre enteros (``math.ceil(x * 10) / 10``
    discrepa de las puntuaciones publicadas cuando el producto se queda un pelo por debajo de una décima)."""
    scaled = int(round(value * 100000))
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (scaled // 10000 + 1) / 10.0


def cvss_score(vector: str) -> float | None:
    """La puntuación base CVSS 3.x de un vector, o ``None`` si no lo es (desconocido no es 0.0: cero es la de una
    vulnerabilidad sin impacto)."""
    text = str(vector or "")
    if not text.upper().startswith("CVSS:3"):
        return None
    parts = {}
    for chunk in text.split("/")[1:]:
        key, _sep, val = chunk.partition(":")
        parts[key.strip().upper()] = val.strip().upper()
    try:
        changed = parts["S"] == "C"
        av, ac, ui = _CVSS_W["AV"][parts["AV"]], _CVSS_W["AC"][parts["AC"]], _CVSS_W["UI"][parts["UI"]]
        pr = _CVSS_PR[changed][parts["PR"]]
        conf, integ, avail = _CVSS_W["C"][parts["C"]], _CVSS_W["I"][parts["I"]], _CVSS_W["A"][parts["A"]]
    except KeyError:
        return None
    iss = 1.0 - ((1.0 - conf) * (1.0 - integ) * (1.0 - avail))
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    total = impact + 8.22 * av * ac * pr * ui
    return _roundup(min(total * 1.08 if changed else total, 10.0))


def rating_of(score: float | None) -> str:
    if score is None:
        return ""
    if score <= 0:
        return "none"
    if score < 4.0:
        return "low"
    if score < 7.0:
        return "moderate"
    return "high" if score < 9.0 else "critical"


def _published_rating(record: dict) -> str:
    """La gravedad que publicó la propia base de datos (los avisos de GitHub la llevan; los PYSEC, no)."""
    raw = str(((record or {}).get("database_specific") or {}).get("severity") or "").lower()
    return "moderate" if raw == "medium" else (raw if raw in RATINGS else "")


def advisory_details(vid: str, timeout: float = TIMEOUT) -> dict:
    """Lo grave que es un aviso y de qué trata, de su propio registro. Nunca lanza."""
    if not advisory_url(vid):
        return {"ok": False, "error": "bad_id"}
    got = _get_json(OSV_VULN_API.format(vid=vid), timeout)
    if not got["ok"]:
        return got
    record = got["data"] if isinstance(got["data"], dict) else {}
    score, vector = None, ""
    for entry in record.get("severity") or []:
        value = cvss_score(entry.get("score")) if isinstance(entry, dict) else None
        if value is not None and (score is None or value > score):
            score, vector = value, str(entry.get("score") or "")
    published = _published_rating(record)
    return {"ok": True, "aliases": [str(a) for a in (record.get("aliases") or []) if a],
            "severity": published or rating_of(score), "published": bool(published), "score": score,
            "vector": vector, "summary": str(record.get("summary") or "")[:300]}


def _pool(fn, items, timeout: float, on_each=None) -> dict:
    """``{item: fn(item)}`` en paralelo y acotado; un fallo es un valor, nunca una excepción hacia arriba.
    ``on_each(hechos)`` tras cada uno (la barra de progreso)."""
    out: dict = {}
    if not items:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fn, item, timeout): item for item in items}
        for fut in concurrent.futures.as_completed(futures):
            try:
                out[futures[fut]] = fut.result()
            except Exception as exc:  # noqa: BLE001
                out[futures[fut]] = {"ok": False, "error": "unreachable", "detail": str(exc)[:200]}
            if on_each is not None:
                on_each(len(out))
    return out


# --------------------------------------------------------------------------- versión más nueva

def version_key(value: str) -> tuple | None:
    """Una versión comparable, o ``None`` si no se puede leer (no es PEP 440: lo honrado es «no se sabe»)."""
    parts = _NUM_RE.findall(str(value or ""))
    return tuple(int(p) for p in parts[:4]) if parts else None


def compare(installed: str, latest: str) -> str:
    """``behind`` / ``current`` / ``unknown``."""
    a, b = version_key(installed), version_key(latest)
    if a is None or b is None:
        return "unknown"
    return "behind" if b > a else "current"


def latest_version(pin: tuple[str, str], timeout: float = TIMEOUT) -> dict:
    """La versión más nueva publicada de ``(ecosistema, nombre)``."""
    ecosystem, name = pin
    if ecosystem not in ECOSYSTEMS or not _NAME_RE.match(str(name or "")):
        return {"ok": False, "error": "bad_name"}
    if ecosystem == "PyPI":
        got = _get_json(PYPI_URL.format(name=name), timeout)
        newest = str(((got.get("data") or {}).get("info") or {}).get("version") or "") if got["ok"] else ""
    else:
        got = _get_json(NPM_URL.format(name=urllib.parse.quote(name, safe="@")), timeout)
        newest = str((got.get("data") or {}).get("version") or "") if got["ok"] else ""
    if not got["ok"]:
        return got
    return {"ok": True, "latest": newest}


# --------------------------------------------------------------------------- vulnerabilidades

def vulnerabilities(rows: list[dict], timeout: float = TIMEOUT) -> dict:
    """Los avisos conocidos de cada ``(ecosistema, nombre, versión)``, en UNA petición a OSV.dev. Por la terna y
    no por el nombre: el mismo nombre puede estar en dos ecosistemas."""
    queries, pins = [], []
    for row in rows:
        if not row.get("installed"):
            continue                        # lo que no está instalado no es vulnerable
        pins.append((row["ecosystem"], row["name"], row["installed"]))
        queries.append({"package": {"name": row["name"], "ecosystem": row["ecosystem"]}, "version": row["installed"]})
    if not queries:
        return {"ok": True, "by_pin": {}, "asked": 0}
    got = _get_json(OSV_BATCH_URL, timeout, json.dumps({"queries": queries}).encode())
    if not got["ok"]:
        return got
    results = (got["data"] or {}).get("results") if isinstance(got["data"], dict) else None
    # La respuesta va en el orden de la pregunta; con otra longitud, emparejar sería nombrar el paquete equivocado
    if not isinstance(results, list) or len(results) != len(pins):
        return {"ok": False, "error": "length_mismatch" if isinstance(results, list) else "not_json"}
    by_pin = {}
    for pin, res in zip(pins, results):
        ids = [str(v.get("id") or "") for v in ((res or {}).get("vulns") or []) if isinstance(v, dict)]
        by_pin[pin] = sorted(i for i in ids if _ID_RE.match(i))   # llegan de la red y acaban en una URL
    return {"ok": True, "by_pin": by_pin, "asked": len(queries)}


def collapse_aliases(ids, details: dict) -> dict:
    """``{identificador: el que lo representa}``: una vulnerabilidad, una entrada (un GHSA, un PYSEC y un CVE del
    mismo fallo contados aparte dirían tres veces más de lo que hay). Gana el que publicó gravedad y, a igualdad,
    el primero por orden, para que la elección no dependa de qué hilo contestó antes."""
    known = {str(i) for i in ids if i}
    parent = {i: i for i in known}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for vid in sorted(known):
        for alias in (details.get(vid) or {}).get("aliases") or []:
            if alias in known:
                a, b = find(vid), find(str(alias))
                if a != b:
                    parent[max(a, b)] = min(a, b)
    groups: dict = {}
    for vid in known:
        groups.setdefault(find(vid), []).append(vid)
    out = {}
    for members in groups.values():
        members.sort(key=lambda v: (0 if (details.get(v) or {}).get("published") else 1, v))
        for member in members:
            out[member] = members[0]
    return out


def _grade(detail) -> dict:
    got = detail or {}
    if not got.get("ok"):
        return {"severity": "", "score": None, "published": False, "summary": ""}
    return {"severity": str(got.get("severity") or ""), "score": got.get("score"),
            "published": bool(got.get("published")), "summary": str(got.get("summary") or "")}


def check(rows: list[dict], timeout: float = TIMEOUT, progress=None) -> dict:
    """Las dos preguntas para cada fila ``{name, installed, ecosystem, group}``: la versión más nueva y los avisos,
    con su gravedad. Devuelve lo que se guarda y enseña (``at``, ``rows``, totales y si OSV contestó).

    ``progress(fase, hechos, total)`` dice por dónde va: ``versions`` (una petición por paquete), ``vulnerabilities``
    (la consulta a OSV.dev, una) y ``details`` (una por aviso distinto, que solo se sabe cuántos son al final)."""
    report = progress or (lambda phase, done, total: None)
    rows = [r for r in rows if r.get("name") and r.get("ecosystem") in ECOSYSTEMS]
    pins = sorted({(r["ecosystem"], r["name"]) for r in rows})
    report("versions", 0, len(pins))
    latest = _pool(latest_version, pins, timeout, on_each=lambda n: report("versions", n, len(pins)))
    report("vulnerabilities", 0, 1)
    vulns = vulnerabilities(rows, timeout)
    by_pin = vulns.get("by_pin") or {} if vulns.get("ok") else {}
    every_id = sorted({i for ids in by_pin.values() for i in ids})
    wanted = every_id[:MAX_DETAILS]
    report("details", 0, len(wanted))
    details = _pool(advisory_details, wanted, timeout, on_each=lambda n: report("details", n, len(wanted)))
    under = collapse_aliases(every_id, details)
    also: dict = {}
    for vid, keeper in under.items():
        if vid != keeper:
            also.setdefault(keeper, []).append(vid)
    out_rows = []
    for row in rows:
        installed = str(row.get("installed") or "")
        got = latest.get((row["ecosystem"], row["name"])) or {}
        newest = str(got.get("latest") or "") if got.get("ok") else ""
        kept = sorted({under.get(i, i) for i in by_pin.get((row["ecosystem"], row["name"], installed)) or []})
        found = [{"id": i, "url": advisory_url(i), "aliases": sorted(also.get(i) or []), **_grade(details.get(i))}
                 for i in kept]
        found.sort(key=lambda v: (-RATINGS.index(v["severity"]) if v["severity"] in RATINGS else 1, v["id"]))
        worst_rank = max((RATINGS.index(v["severity"]) for v in found if v["severity"] in RATINGS), default=0)
        out_rows.append({"name": row["name"], "ecosystem": row["ecosystem"], "group": row.get("group", ""),
                         "kind": KINDS.get(row["ecosystem"], row["ecosystem"]),
                         "installed": installed, "latest": newest,
                         "state": compare(installed, newest) if newest else "unknown",
                         "url": project_url(row["ecosystem"], row["name"], newest) if newest else "",
                         "error": "" if got.get("ok") else str(got.get("error") or ""), "vulns": found,
                         # Para ordenar la columna: la peor gravedad pesa más que el número de avisos
                         "risk": worst_rank * 1000 + len(found)})
    # Los vulnerables primero; luego los atrasados; luego por nombre
    out_rows.sort(key=lambda r: (not r["vulns"], r["state"] != "behind", r["name"].lower()))
    severities = [v["severity"] for r in out_rows for v in r["vulns"]]
    return {"at": now_iso(), "rows": out_rows,
            "checked": len(out_rows), "behind": sum(1 for r in out_rows if r["state"] == "behind"),
            "vulns_ok": bool(vulns.get("ok")), "vulns_error": "" if vulns.get("ok") else str(vulns.get("error") or ""),
            "vuln_asked": int(vulns.get("asked") or 0) if vulns.get("ok") else 0,
            # DISTINTOS: el mismo aviso en dos filas es un aviso
            "vuln_total": len({v["id"] for r in out_rows for v in r["vulns"]}),
            "vuln_packages": sum(1 for r in out_rows if r["vulns"]),
            "worst": max(severities, key=lambda s: RATINGS.index(s) if s in RATINGS else -1) if severities else ""}


# --------------------------------------------------------------------------- aviso del Resumen

@source("advisories", order=45)
def _vulnerable_packages(ctx):
    """Si la última comprobación encontró vulnerabilidades, se dice en el Resumen hasta la siguiente."""
    last = (ctx.maint_state or {}).get(STATE_KEY) or {}
    total = int(last.get("vuln_total") or 0)
    if not total:
        return []
    when = str(last.get("at") or "")[:10]
    level = "danger" if last.get("worst") in ("high", "critical") else "warn"
    return [alert(level, "vulnerable_packages",
                  ngettext("%(num)s known vulnerability in the installed libraries",
                           "%(num)s known vulnerabilities in the installed libraries", total),
                  _("Found in the check of %(date)s. Update those libraries and check again.", date=when),
                  "vulnerabilities", _("See the libraries"), "advisories")]


# --------------------------------------------------------------------------- qué se comprueba

def default_rows(vendor_dir: Path = VENDOR_DIR) -> list[dict]:
    """Lo que se comprueba, decidido aquí y nunca por quien lo pide: todo lo instalado en el entorno de Python (con lo
    que lo pide: StorageWeb, un extra o nadie a mano) y las bibliotecas de JavaScript copiadas (con su nombre en
    OSV)."""
    comp = diagnostics.components()
    group = {diagnostics.canonical(r["name"]): "required" for r in comp["required"]}
    group.update({diagnostics.canonical(r["name"]): "optional" for r in comp["optional"]})
    rows = [{"name": p["name"], "installed": p["version"], "ecosystem": "PyPI",
             "group": group.get(diagnostics.canonical(p["name"]), "other")}
            for p in diagnostics.installed_packages() if diagnostics.canonical(p["name"]) != diagnostics.DISTRIBUTION]
    rows += [{"name": lib["advisories"], "installed": lib["version"], "ecosystem": "npm", "group": "javascript"}
             for lib in diagnostics.vendored(vendor_dir)]
    return rows


# --------------------------------------------------------------------------- la comprobación en marcha
#
# Tarda (decenas de peticiones a internet), así que va en un hilo y no ata una petición ni depende de que la página
# siga abierta. Una a la vez para todo el proceso (Waitress es un proceso): el botón y la tarea periódica comparten
# este estado, y la barra de progreso lo lee. Si el servicio se reinicia a medias, se pierde la comprobación, no el
# último resultado (que está en la base de datos).

_JOB_LOCK = threading.Lock()
_JOB: dict = {"running": False}
# Peso de cada fase en la barra: las versiones son casi todo; luego la consulta a OSV y el detalle de cada aviso
_WEIGHTS = {"versions": (0, 70), "vulnerabilities": (70, 10), "details": (80, 20)}


def job_status() -> dict:
    """``running``, ``phase``, ``done``, ``total``, ``percent``, ``started``, ``by`` y, al acabar, ``finished`` y
    ``summary``."""
    with _JOB_LOCK:
        job = dict(_JOB)
    base, span = _WEIGHTS.get(job.get("phase", ""), (0, 0))
    total = job.get("total") or 0
    job["percent"] = 100 if job.get("finished") and not job["running"] else int(
        base + (span * job.get("done", 0) / total if total else 0))
    return job


def try_start(by: str, total: int = 0) -> bool:
    """Reserva la comprobación para ``by``; ``False`` si ya hay una en marcha (no empieza otra)."""
    with _JOB_LOCK:
        if _JOB.get("running"):
            return False
        _JOB.clear()
        _JOB.update(running=True, phase="versions", done=0, total=total, by=by,
                    started=now_iso())
        return True


def run_job(rows: list[dict], database: str, username: str, ip: str | None = None) -> dict:
    """La comprobación reservada con :func:`try_start`: comprobar, guardar el resultado, auditarlo y apuntar que acabó
    pase lo que pase (un fallo no puede dejar el botón bloqueado para siempre). Devuelve el resumen."""
    def progress(phase: str, done: int, total: int) -> None:
        with _JOB_LOCK:
            _JOB.update(phase=phase, done=done, total=total)

    summary: dict = {}
    try:
        result = check(rows, progress=progress)
        summary = {k: result[k] for k in ("vuln_total", "vuln_packages", "behind", "vulns_ok", "vulns_error")}
        conn = connect(database)
        try:
            maintenance.put_state(conn, STATE_KEY, result)
            audit.log(conn, "dependencies_checked", username=username, ip=ip,
                      detail=f"packages={result['checked']} vulnerable={result['vuln_packages']} "
                             f"advisories={result['vuln_total']} behind={result['behind']}"
                             + ("" if result["vulns_ok"] else f" error={result['vulns_error']}"))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        _log.exception("The dependency check failed")
        summary = {"vulns_ok": False, "vulns_error": "failed"}
    finally:
        with _JOB_LOCK:
            _JOB.update(running=False, finished=now_iso(),
                        summary=summary)
    return summary


@maintenance.task("dependency_check", every=lambda cfg: cfg["security"].get("dependency_check_hours") or 0, order=60)
def _periodic_check(conn, cfg: dict) -> None:
    """La comprobación automática (``security.dependency_check_hours``): la misma que el botón, como ``system``. Si
    ya hay una en marcha (alguien pulsó el botón), esta vez no se hace."""
    rows = default_rows()
    if try_start("system", len(rows)):
        run_job(rows, cfg["database"], "system")

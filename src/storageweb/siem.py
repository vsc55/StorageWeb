"""Reenvío de la auditoría a un SIEM (``audit.*``): syslog (UDP, TCP o TLS) y un fichero JSON por líneas.

Cada evento que se escribe en ``audit_log`` (``db/repositories/audit.log``) se pone también en una cola que vacía
un hilo aparte, así que una red lenta o un colector caído nunca frenan una petición: si la cola se llena, los
eventos que no caben se cuentan como perdidos (en la auditoría de la base de datos siguen estando todos).

Formatos del syslog (``audit.syslog_format``), todos con cabecera RFC 5424:

- ``rfc5424``: los campos como datos estructurados (``[storageweb@32473 user="ana" ip="…" …]``) y un texto.
- ``json``: el mensaje es el evento en JSON (Graylog, Logstash, Wazuh…).
- ``cef``: el mensaje en Common Event Format (ArcSight, QRadar, Microsoft Sentinel…).

Por TCP cada mensaje va en una línea; por TLS, con su longitud delante (RFC 5425). El fichero JSON (una línea
por evento) es para un agente que lo lea (Filebeat, Fluent Bit, el de Wazuh…); se abre y se cierra en cada
escritura, así que se puede rotar con logrotate. Sin dependencias.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, audit_levels, metrics
from .settings.defaults import AUDIT_FORMATS as FORMATS
from .settings.defaults import SYSLOG_FACILITIES as FACILITIES
from .settings.defaults import SYSLOG_PORTS as SCHEMES
QUEUE_SIZE = 10000
TIMEOUT = 5.0
SD_ID = "storageweb@32473"      # 32473: número de empresa reservado para ejemplos (RFC 5612)
_log = logging.getLogger(__name__)
# Nivel del evento (audit_levels) → severidad de syslog (RFC 5424) y de CEF (0-10)
SYSLOG_SEVERITY = {"debug": 7, "info": 6, "warning": 4, "error": 3, "critical": 2}
CEF_SEVERITY = {"debug": 1, "info": 3, "warning": 6, "error": 8, "critical": 10}


def severity(event: dict) -> int:
    """La severidad de syslog del evento, por su nivel (el de su acción si no lo trae)."""
    level = event.get("level") or audit_levels.level_of(event["action"], event.get("detail"))
    return SYSLOG_SEVERITY.get(level, 6)


def parse_target(url: str) -> tuple[str, str, int]:
    """``udp://host:514`` → ``("udp", "host", 514)``. :class:`ValueError` si no vale."""
    parts = urlsplit(url.strip())
    if parts.scheme not in SCHEMES or not parts.hostname or parts.path not in ("", "/"):
        raise ValueError(url)
    return parts.scheme, parts.hostname, parts.port or SCHEMES[parts.scheme]


# --------------------------------------------------------------------------- formatos

def _sd_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")


def _cef_header(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _cef_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace("\r", " ").replace("\n", " ")


def _msgid(action: str) -> str:
    clean = "".join(c for c in action if 33 <= ord(c) <= 126)
    return clean[:32] or "-"


def format_syslog(event: dict, fmt: str, facility: str = "local0", host: str | None = None) -> str:
    """El evento como mensaje syslog RFC 5424 (sin el entramado del transporte)."""
    pri = FACILITIES.get(facility, FACILITIES["local0"]) * 8 + severity(event)
    stamp = event.get("ts") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    head = f"<{pri}>1 {stamp} {host or socket.gethostname() or '-'} storageweb {os.getpid()} {_msgid(event['action'])}"
    fields = {k: event.get(k) for k in ("level", "user", "ip", "target", "detail") if event.get(k)}
    if fmt == "json":
        return f"{head} - {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}"
    if fmt == "cef":
        ext = {"rt": stamp, "suser": event.get("user"), "src": event.get("ip"), "fname": event.get("target"),
               "msg": event.get("detail")}
        extension = " ".join(f"{k}={_cef_value(str(v))}" for k, v in ext.items() if v)
        sev = CEF_SEVERITY.get(event.get("level") or audit_levels.level_of(event["action"], event.get("detail")), 3)
        cef = (f"CEF:0|StorageWeb|StorageWeb|{_cef_header(__version__)}|{_cef_header(event['action'])}|"
               f"{_cef_header(event['action'])}|{sev}|{extension}")
        return f"{head} - {cef}"
    sd = "[" + SD_ID + "".join(f' {k}="{_sd_value(str(v))}"' for k, v in fields.items()) + "]"
    text = " ".join(str(v) for v in (event.get("user"), event["action"], event.get("target")) if v)
    return f"{head} {sd} {text}"


def event_of(ts: str, username, action: str, target, ip, detail, level: str | None = None) -> dict:
    return {"ts": ts, "level": level or audit_levels.level_of(action, detail), "user": username, "action": action,
            "target": target, "ip": ip, "detail": detail, "app": "storageweb"}


# --------------------------------------------------------------------------- envío

class _Sender:
    """Una conexión al colector (o un fichero). Se reabre sola tras un error."""

    def __init__(self, options: dict):
        self.options = options
        self.sock: socket.socket | None = None

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _connect(self) -> socket.socket:
        scheme, host, port = parse_target(self.options["syslog"])
        if scheme == "udp":
            sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(TIMEOUT)
            sock.connect((host, port))
            return sock
        sock = socket.create_connection((host, port), timeout=TIMEOUT)
        if scheme == "tls":
            context = ssl.create_default_context(cafile=self.options.get("syslog_ca") or None)
            if not self.options.get("tls_verify", True):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock, server_hostname=host)
        return sock

    def send(self, event: dict) -> None:
        if self.options.get("syslog"):
            message = format_syslog(event, self.options.get("syslog_format", "rfc5424"),
                                    self.options.get("syslog_facility", "local0")).encode("utf-8")
            scheme = parse_target(self.options["syslog"])[0]
            if scheme == "tls":
                frame = str(len(message)).encode() + b" " + message       # RFC 5425: con la longitud delante
            elif scheme == "tcp":
                frame = message.replace(b"\n", b" ") + b"\n"
            else:
                frame = message
            for attempt in (1, 2):    # una conexión TCP vieja puede estar cerrada: se reintenta una vez
                try:
                    if self.sock is None:
                        self.sock = self._connect()
                    self.sock.sendall(frame) if scheme != "udp" else self.sock.send(frame)
                    break
                except OSError:
                    self.close()
                    if attempt == 2 or scheme == "udp":
                        raise
        if self.options.get("file"):
            path = Path(self.options["file"])
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


class Forwarder:
    """La cola y el hilo que la vacía. Uno por proceso (:data:`FORWARDER`)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._options: dict = {}
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self._thread: threading.Thread | None = None
        self._sender: _Sender | None = None
        self.sent = self.dropped = self.errors = 0
        self.last_error = ""
        self.last_error_at = ""
        self.last_ok_at = ""

    @property
    def active(self) -> bool:
        return bool(self._options.get("syslog") or self._options.get("file"))

    def configure(self, options: dict | None) -> None:
        """Aplica ``audit.*`` (barato si no cambió: se llama en cada petición)."""
        wanted = {k: v for k, v in (options or {}).items()}
        if wanted == self._options:
            return
        with self._lock:
            if self._sender is not None:
                self._sender.close()
            self._options = wanted
            self._sender = _Sender(wanted) if self.active else None
            if self.active and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, name="storageweb-audit-forward", daemon=True)
                self._thread.start()

    def emit(self, event: dict) -> None:
        if not self.active:
            return
        if not audit_levels.at_least(event.get("level", "info"), self._options.get("forward_min_level", "info")):
            return      # por debajo de audit.forward_min_level: se guarda, pero no se reenvía
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1
            metrics.inc("storageweb_audit_forward_dropped_total")

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            try:
                with self._lock:
                    sender = self._sender
                if sender is not None:
                    sender.send(event)
                    self.sent += 1
                    self.last_ok_at = _now()
            except Exception as exc:  # noqa: BLE001 (el hilo no puede morir: se apunta y se sigue)
                self._failed(exc)
            finally:
                self._queue.task_done()

    def _failed(self, exc: Exception) -> None:
        self.errors += 1
        metrics.inc("storageweb_audit_forward_errors_total")
        message = str(exc) or exc.__class__.__name__
        if message != self.last_error:     # no llenar el registro con el mismo error en cada evento
            _log.warning("Could not forward the audit log: %s", message)
        self.last_error, self.last_error_at = message, _now()

    def flush(self, timeout: float = 3.0) -> None:
        """Espera (como mucho ``timeout`` segundos) a que salga lo que hay en la cola (al acabar la CLI)."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)

    def test(self, options: dict) -> str | None:
        """Envía un evento de prueba sin pasar por la cola. El error o ``None``."""
        sender = _Sender(options)
        try:
            sender.send(event_of(_now(), None, "audit_forward_test", None, None, "StorageWeb", "info"))
        except Exception as exc:  # noqa: BLE001 (DNS, red, certificado…: se muestra tal cual)
            return str(exc) or exc.__class__.__name__
        finally:
            sender.close()
        return None

    def status(self) -> dict:
        return {"active": self.active, "sent": self.sent, "dropped": self.dropped, "errors": self.errors,
                "queued": self._queue.qsize(), "last_error": self.last_error, "last_error_at": self.last_error_at,
                "last_ok_at": self.last_ok_at,
                "failing": bool(self.last_error_at and self.last_error_at >= (self.last_ok_at or ""))}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


FORWARDER = Forwarder()
configure = FORWARDER.configure
emit = FORWARDER.emit

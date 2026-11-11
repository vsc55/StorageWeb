"""Utilidades de seguridad: CSRF, límite de intentos, rutas y nombres seguros."""
from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
import time
import unicodedata
from functools import wraps
from pathlib import Path

from flask import abort, g, redirect, request, session, url_for

# --------------------------------------------------------------------------- CSRF


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def check_csrf() -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    expected = session.get("_csrf")
    sent = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
    if not expected or not sent or not hmac.compare_digest(expected, sent):
        abort(400, description="Token CSRF inválido. Recarga la página e inténtalo de nuevo.")


# --------------------------------------------------------------------------- login


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapper


def safe_next(target: str | None) -> str:
    """Evita open-redirects: solo se aceptan rutas relativas del propio sitio."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("files.index")
    return target


class LoginThrottle:
    """Bloqueo temporal tras N intentos fallidos (por IP y por usuario). En memoria."""

    def __init__(self, max_failures: int, lockout_seconds: int):
        self.max_failures = max_failures
        self.lockout = lockout_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _keys(self, ip: str, username: str) -> list[str]:
        return [f"ip:{ip}", f"user:{username.lower()}"]

    def _prune(self, key: str, now: float) -> list[float]:
        items = [t for t in self._fails.get(key, []) if now - t < self.lockout]
        if items:
            self._fails[key] = items
        else:
            self._fails.pop(key, None)
        return items

    def is_blocked(self, ip: str, username: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._prune(k, now)) >= self.max_failures for k in self._keys(ip, username))

    def failure(self, ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in self._keys(ip, username):
                self._prune(k, now)
                self._fails.setdefault(k, []).append(now)

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._fails.pop(f"user:{username.lower()}", None)


# --------------------------------------------------------------------------- nombres y rutas

_INVALID_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}
UPLOAD_TMP_PREFIX = ".sw-upload-"


def safe_filename(name: str) -> str:
    """Sanea un nombre de archivo/carpeta conservando acentos y espacios."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]
    name = _INVALID_CHARS.sub("_", name).strip().rstrip(". ")
    if name in ("", ".", "..") or name.startswith(UPLOAD_TMP_PREFIX):
        raise ValueError("Nombre de archivo no válido")
    if os.name == "nt" and name.split(".")[0].upper() in _WIN_RESERVED:
        raise ValueError("Nombre reservado en Windows")
    encoded = name.encode("utf-8")
    if len(encoded) > 255:
        stem, dot, ext = name.rpartition(".")
        if not dot or len(ext) > 16:
            stem, ext = name, ""
        budget = 255 - len(ext.encode("utf-8")) - (1 if ext else 0)
        stem = stem.encode("utf-8")[:budget].decode("utf-8", "ignore")
        name = f"{stem}.{ext}" if ext else stem
    return name


def safe_username_for_path(username: str) -> str:
    """Nombre de usuario apto para usarse como nombre de carpeta."""
    cleaned = re.sub(r"[^A-Za-z0-9._@-]", "_", unicodedata.normalize("NFC", username.lower()))
    cleaned = cleaned.strip(".")
    if not cleaned:
        raise ValueError("Nombre de usuario no válido para ruta")
    return cleaned


def resolve_inside(base: Path, sub: str) -> Path:
    """Devuelve base/sub garantizando que no escapa de base (incluye symlinks)."""
    base = base.resolve()
    parts = [p for p in sub.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        abort(404)
    target = base.joinpath(*parts).resolve() if parts else base
    if target != base and base not in target.parents:
        abort(404)
    return target


def set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self' https://login.microsoftonline.com; base-uri 'self'",
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response

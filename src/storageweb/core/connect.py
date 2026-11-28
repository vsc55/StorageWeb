"""Conectar una aplicación (la extensión de VS Code) iniciando sesión en el navegador.

Así la aplicación consigue un token de API sin que el usuario lo copie a mano, y con el inicio de sesión
de la web (también Entra ID, sin escribir nada en un equipo unido). Es el flujo de OAuth con PKCE:

1. La aplicación inventa un ``verifier`` secreto, abre en el navegador ``/connect/<cliente>`` con su
   SHA-256 (``challenge``), un ``state`` y la dirección de vuelta (``redirect_uri``).
2. El usuario, con su sesión, acepta. StorageWeb apunta un **código** de un solo uso (unos minutos) y
   manda el navegador a ``redirect_uri?code=…&state=…`` (la aplicación lo recibe).
3. La aplicación canjea el código **con el verifier** en ``/connect/token`` y recibe el token. Otro
   programa que capture la vuelta no tiene el verifier y no puede canjearlo.

Las direcciones de vuelta están fijadas por cliente (``CLIENTS``): nunca se manda un código a una web
cualquiera. El token se crea al canjear (si no se canjea, no hay token) y se ve en *Mi perfil*.
Los códigos pendientes viven en memoria de este proceso.
"""
from __future__ import annotations

import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass
from sqlite3 import Connection
from urllib.parse import urlencode

from ..db.repositories import users
from ..i18n import _
from . import tokens
from ..text import pkce_challenge

CODE_SECONDS = 300
MAX_PENDING = 1000

_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")          # base64url de un SHA-256, sin «=»
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")      # RFC 7636
_STATE = re.compile(r"[A-Za-z0-9._~-]{16,128}")


class ConnectError(Exception):
    pass


@dataclass(frozen=True)
class Client:
    key: str
    label: str
    redirect: re.Pattern[str]


CLIENTS = {
    "vscode": Client("vscode", "Visual Studio Code",
                     re.compile(r"(vscode|vscode-insiders|vscodium)://storageweb\.storageweb-sync/auth")),
}


@dataclass(frozen=True)
class Grant:
    user_id: int
    client: str
    device: str
    challenge: str
    scope: str
    days: int
    expires: float


_PENDING: dict[str, Grant] = {}
_LOCK = threading.Lock()


def clean_device(value: str | None) -> str:
    """El nombre del equipo que manda la aplicación (para el nombre del token): sin caracteres raros."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    return re.sub(r" +", " ", re.sub(r"[^\w .@-]", "", text))[:40].strip()


def check_request(client: str, redirect_uri: str | None, challenge: str | None, state: str | None) -> Client:
    """Valida lo que pide la aplicación. Lanza ConnectError si algo no cuadra (no se redirige a ningún sitio)."""
    found = CLIENTS.get(client)
    if found is None:
        raise ConnectError(_("Unknown application."))
    if not redirect_uri or not found.redirect.fullmatch(redirect_uri):
        raise ConnectError(_("The return address is not allowed for this application."))
    if not challenge or not _CHALLENGE.fullmatch(challenge) or not state or not _STATE.fullmatch(state):
        raise ConnectError(_("Incomplete request: start again from the application."))
    return found


def _purge(now: float) -> None:
    for code in [c for c, g in _PENDING.items() if g.expires < now]:
        del _PENDING[code]


def issue(user_id: int, client: Client, device: str, challenge: str, *, scope: str, days: int,
          max_days: int = 0) -> str:
    """El usuario aceptó: devuelve el código de un solo uso para la vuelta."""
    if scope not in tokens.SCOPES or days not in tokens.allowed_days(max_days):
        raise ConnectError(_("Invalid scope or expiry."))
    code = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _LOCK:
        _purge(now)
        if len(_PENDING) >= MAX_PENDING:
            raise ConnectError(_("Too many pending authorizations. Try again in a few minutes."))
        _PENDING[code] = Grant(user_id, client.key, device, challenge, scope, days, now + CODE_SECONDS)
    return code


def back_url(redirect_uri: str, **params: str) -> str:
    return f"{redirect_uri}?{urlencode(params)}"


challenge_of = pkce_challenge


def redeem(conn: Connection, code: str | None, verifier: str | None, max_days: int = 0):
    """Canjea el código (una sola vez, se acierte o no). Devuelve (usuario, token en claro, nombre, días)."""
    with _LOCK:
        grant = _PENDING.pop(code or "", None)
    if grant is None or grant.expires < time.monotonic():
        raise ConnectError("invalid_grant")
    if not verifier or not _VERIFIER.fullmatch(verifier) \
            or not hmac.compare_digest(challenge_of(verifier), grant.challenge):
        raise ConnectError("invalid_grant")
    user = users.get_by_id(conn, grant.user_id)
    if user is None or not user["enabled"]:
        raise ConnectError("invalid_grant")
    plain, name, days = _token_for(conn, user, CLIENTS[grant.client], grant.device, grant.scope, grant.days, max_days)
    return user, plain, name, days


# Entrar con la cuenta del sistema (sin la página de permitir): más corto que el de serie de esa página, porque
# volver a entrar no pregunta nada (Windows ya sabe la cuenta) y un token de Microsoft robado o pedido con engaños
# (código de dispositivo con el client id de VS Code) da menos tiempo
DESKTOP_DAYS = 90


def desktop_token(conn: Connection, user, client: str, device: str, max_days: int = 0) -> tuple[str, str, int]:
    """El token de API de una aplicación que entró con la cuenta del sistema (``/connect/desktop``): de lectura y
    escritura, para el equipo ``device``. Devuelve (token en claro, nombre, días). :class:`ConnectError` si
    ``client`` no es una aplicación conocida."""
    app = CLIENTS.get(client)
    if app is None:
        raise ConnectError("unknown_client")
    return _token_for(conn, user, app, clean_device(device), "write", DESKTOP_DAYS, max_days)


def _token_for(conn: Connection, user, app: Client, device: str, scope: str, days: int, max_days: int):
    """El token de API de una aplicación conectada, con su nombre («Visual Studio Code (PC-ANA)»)."""
    name = (f"{app.label} ({device})" if device else app.label)[:80]
    days = tokens.clamp_days(days, max_days)   # la política pudo cambiar entre medias
    plain, _token_id = tokens.create(conn, user, name=name, scope=scope, days=days, max_days=max_days)
    return plain, name, days


def clear() -> None:
    """Para los tests."""
    with _LOCK:
        _PENDING.clear()

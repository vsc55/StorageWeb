"""Verificación en dos pasos (TOTP): alta, comprobación, códigos de recuperación y política. Sin Flask.

Basado en el de ServiceSentry (mismo autor). Las piezas:

* :mod:`.totp`: la aritmética del RFC 6238; :mod:`.qr`: el código QR, escrito aquí (ISO/IEC 18004).
* este módulo: **qué** pasa (dar de alta, comprobar un código, gastar uno de recuperación) y **a quién** se le pide.
  Recibe una conexión y la clave de los secretos y devuelve datos: todo lo importante («un código vale una vez»,
  «un código de recuperación se gasta», «un alta a medias no protege nada») se prueba sin aplicación ni navegador.

Las reglas de fondo:

* **Un alta no da nada hasta que se demuestra.** Empezarla guarda una fila sin confirmar, para dibujar el QR con la
  misma semilla que se comprobará; todo pide un factor confirmado.
* **Solo los métodos con contraseña** (cuentas locales, PAM). Quien entra con un proveedor SSO (Microsoft Entra ID)
  pasa por el segundo factor de ese proveedor; pedirle otro sería repetir lo mismo.
* **Una cuenta con factor lo usa siempre**, diga lo que diga la política: apagarla no puede dejar de pedir en silencio
  lo que alguien configuró. La política solo decide a quién se le **exige** tenerlo (y quien lo debe y no lo tiene lo
  configura al entrar, nunca se queda fuera).
* **La semilla se guarda cifrada** con la clave de los secretos (como los demás secretos) y de los códigos de
  recuperación solo el hash.
* **Nada dice por qué falló.** Un código equivocado y uno ya gastado contestan igual; el porqué va a la auditoría.
"""
from __future__ import annotations

import secrets
from sqlite3 import Connection

from werkzeug.security import check_password_hash, generate_password_hash

from ... import providers
from ...db.repositories import mfa as repo
from ...settings import secretbox
from . import qr, totp

# Diez códigos: bastan para perder alguno y seguir teniendo cómo entrar, y son pocos para que la lista se guarde.
RECOVERY_COUNT = 10
# Dos grupos de cinco con un alfabeto sin 0/O ni 1/I/l: se apuntan y se vuelven a leer, y los caracteres que se
# confunden son los que convierten un código que funciona en una consulta al soporte. 50 bits por código.
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_RECOVERY_GROUP = 5


# --------------------------------------------------------------------------- a quién

def applies(user) -> bool:
    """Si la cuenta puede usar la verificación en dos pasos: las que entran con contraseña (locales, PAM)."""
    method = providers.get(user["source"])
    return method is not None and method.password and not method.sso


def required(cfg: dict, user) -> bool:
    """Si la política (``security.mfa_required``) exige a esta cuenta tenerla."""
    policy = cfg["security"]["mfa_required"]
    return applies(user) and (policy == "all" or (policy == "admins" and user["role"] == "admin"))


def needed(conn: Connection, cfg: dict, user) -> str:
    """Qué le falta a un inicio de sesión con contraseña correcta: ``"verify"`` (tiene factor: el código),
    ``"enrol"`` (la política se lo exige y no tiene: configurarlo ahora) o ``""`` (nada)."""
    if not applies(user):
        return ""
    if enrolled(conn, user):
        return "verify"
    return "enrol" if required(cfg, user) else ""


def enrolled(conn: Connection, user) -> bool:
    row = repo.factor(conn, user["id"])
    return bool(row and row["confirmed"])


def status(conn: Connection, user) -> dict:
    """Lo que necesitan el perfil y la administración, y nada más: nunca la semilla, ni cifrada."""
    row = repo.factor(conn, user["id"])
    active = bool(row and row["confirmed"])
    return {"enrolled": active, "pending": bool(row and not row["confirmed"]),
            "since": row["updated_at"] if active else "",
            "recovery_left": repo.recovery_left(conn, user["id"]) if active else 0}


# --------------------------------------------------------------------------- alta

def _setup(secret: str, user, issuer: str) -> dict:
    uri = totp.provisioning_uri(secret, user["username"], issuer)
    # El QR y la semilla, siempre los dos: el QR es lo que usa todo el mundo, y la semilla la mitad que se puede leer
    # y comprobar, y la única que queda si la cámara no enfoca. svg vacío si el enlace no cabe: se enseña la semilla.
    return {"secret": secret, "secret_groups": totp.secret_groups(secret), "uri": uri, "svg": qr.svg(uri),
            "digits": totp.DIGITS, "period": totp.PERIOD}


def enroll_begin(conn: Connection, key: bytes | None, user, issuer: str) -> dict:
    """Empieza un alta: semilla nueva (sin confirmar), con su QR. Volver a empezar sustituye la pendiente: quien cerró
    la página a medias recibe una semilla nueva, no la que puede estar en una captura de pantalla."""
    if key is None:
        raise secretbox.SecretError("no secrets key")
    secret = totp.secret_new()
    repo.begin(conn, user["id"], secretbox.encrypt(key, secret))
    return _setup(secret, user, issuer)


def pending_setup(conn: Connection, key: bytes | None, user, issuer: str) -> dict | None:
    """El alta pendiente otra vez (al recargar la página), o ``None`` si no hay ninguna."""
    row = repo.factor(conn, user["id"])
    if not row or row["confirmed"]:
        return None
    try:
        return _setup(secretbox.decrypt(key, row["secret"]), user, issuer)
    except secretbox.SecretError:
        return None


def enroll_confirm(conn: Connection, key: bytes | None, user, code: str, *, now: float | None = None) -> list[str]:
    """Comprueba un alta pendiente con un código de la aplicación y la activa. Devuelve los códigos de recuperación en
    claro (la única vez que existen como texto) o ``[]`` si el código no vale.

    El paso que la comprobó queda gastado: si no, lo primero que haría el factor nuevo sería aceptar otra vez el
    código que lo creó. Los códigos se generan aquí y no al empezar: un alta abandonada dejaría un juego funcionando.
    """
    row = repo.factor(conn, user["id"])
    if not row or row["confirmed"]:
        return []
    try:
        secret = secretbox.decrypt(key, row["secret"])
    except secretbox.SecretError:
        return []
    step = totp.verify(secret, code, now=now, after_step=row["last_step"])
    if step is None or not repo.confirm(conn, user["id"], step):
        return []
    return _new_recovery(conn, user)


# --------------------------------------------------------------------------- comprobar

def verify(conn: Connection, key: bytes | None, user, code: str, *, now: float | None = None) -> str:
    """``"totp"``, ``"recovery"`` o ``""``: qué fue el código, si fue algo.

    Primero como TOTP y solo después como código de recuperación, para que seis dígitos nunca gasten uno. Los dos
    caminos gastan lo que usan, y de forma atómica (``note_step``, ``consume_recovery``).
    """
    row = repo.factor(conn, user["id"])
    if not row or not row["confirmed"]:
        return ""
    try:
        secret = secretbox.decrypt(key, row["secret"])
    except secretbox.SecretError:
        secret = ""   # sin la clave de entonces: solo valen los códigos de recuperación
    step = totp.verify(secret, code, now=now, after_step=row["last_step"]) if secret else None
    if step is not None:
        return "totp" if repo.note_step(conn, user["id"], step) else ""
    got = _normalise(code)
    if not got:
        return ""
    for item in repo.recovery_unused(conn, user["id"]):
        if check_password_hash(item["code_hash"], got):
            return "recovery" if repo.consume_recovery(conn, item["id"]) else ""
    return ""


# --------------------------------------------------------------------------- códigos de recuperación y baja

def _normalise(code: str) -> str:
    """Un código de recuperación como se generó, haga lo que haga el teclado (espacios, guion, minúsculas)."""
    return "".join(str(code or "").split()).replace("-", "").upper()


def _new_recovery(conn: Connection, user) -> list[str]:
    def one() -> str:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_GROUP * 2))
        return f"{raw[:_RECOVERY_GROUP]}-{raw[_RECOVERY_GROUP:]}"
    codes = [one() for _ in range(RECOVERY_COUNT)]
    # Con el mismo hash que las contraseñas: lo guardado no permite volver a enseñarlos.
    repo.set_recovery(conn, user["id"], [generate_password_hash(_normalise(c)) for c in codes])
    return codes


def recovery_regenerate(conn: Connection, user) -> list[str]:
    """Un juego nuevo que sustituye entero al anterior; ``[]`` si no hay factor activo."""
    return _new_recovery(conn, user) if enrolled(conn, user) else []


def disable(conn: Connection, user) -> bool:
    """Quita el factor y sus códigos. Devuelve si había. (Las semillas se vuelven a cifrar con otra clave en
    ``settings.secretbox.rekey``, junto con los demás secretos.)"""
    return repo.delete(conn, user["id"])

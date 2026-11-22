"""Verificación en dos pasos (app de códigos TOTP y passkeys): alta, comprobación, códigos de recuperación y
política. Sin Flask.

Basado en el de ServiceSentry (mismo autor). Las piezas:

* :mod:`.totp`: la aritmética del RFC 6238; :mod:`.qr`: el código QR, escrito aquí (ISO/IEC 18004).
* :mod:`.webauthn` (con :mod:`.cbor` y :mod:`.cose`): las ceremonias de las passkeys.
* este módulo: **qué** pasa (dar de alta, comprobar un código o una passkey, gastar uno de recuperación) y **a quién**
  se le pide. Recibe una conexión y la clave de los secretos y devuelve datos: todo lo importante («un código vale una
  vez», «un código de recuperación se gasta», «un alta a medias no protege nada») se prueba sin aplicación ni
  navegador.

Las reglas de fondo:

* **Una cuenta puede tener la app de códigos, una o varias passkeys, o las dos**; cualquiera completa el segundo
  paso. Los códigos de recuperación son **de la cuenta**: sirven con cualquier factor, se generan con el primero y se
  borran con el último.
* **Un alta no da nada hasta que se demuestra.** Empezar la de la app guarda una fila sin confirmar, para dibujar el
  QR con la misma semilla que se comprobará; una passkey se guarda solo tras verificar su registro firmado.
* **Solo los métodos con contraseña** (cuentas locales, PAM). Quien entra con un proveedor SSO (Microsoft Entra ID)
  pasa por el segundo factor de ese proveedor; pedirle otro sería repetir lo mismo.
* **Una cuenta con factor lo usa siempre**, diga lo que diga la política: apagarla no puede dejar de pedir en silencio
  lo que alguien configuró. La política solo decide a quién se le **exige** tenerlo (y quien lo debe y no lo tiene lo
  configura al entrar, nunca se queda fuera).
* **La semilla se guarda cifrada** con la clave de los secretos (como los demás secretos), de los códigos de
  recuperación solo el hash y de las passkeys solo la clave pública.
* **Nada dice por qué falló.** Un código equivocado y uno ya gastado contestan igual; el porqué va a la auditoría.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from sqlite3 import Connection

from werkzeug.security import check_password_hash, generate_password_hash

from ... import providers
from ...db.repositories import mfa as repo
from ...settings import secretbox
from . import cbor, cose, qr, totp, webauthn

# Diez códigos: bastan para perder alguno y seguir teniendo cómo entrar, y son pocos para que la lista se guarde.
RECOVERY_COUNT = 10
# Dos grupos de cinco con un alfabeto sin 0/O ni 1/I/l: se apuntan y se vuelven a leer, y los caracteres que se
# confunden son los que convierten un código que funciona en una consulta al soporte. 50 bits por código.
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_RECOVERY_GROUP = 5

PASSKEY_NAME_MAX = 64
# Lo que vive un challenge de passkey (y el ``timeout`` que se le da al navegador)
CHALLENGE_SECONDS = 300


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
    """Qué le falta a un inicio de sesión con contraseña correcta: ``"verify"`` (tiene factor: el código o la
    passkey), ``"enrol"`` (la política se lo exige y no tiene: configurarlo ahora) o ``""`` (nada)."""
    if not applies(user):
        return ""
    if enrolled(conn, user):
        return "verify"
    return "enrol" if required(cfg, user) else ""


def has_totp(conn: Connection, user) -> bool:
    row = repo.factor(conn, user["id"])
    return bool(row and row["confirmed"])


def enrolled(conn: Connection, user) -> bool:
    """Si la cuenta tiene algún segundo factor activo: la app de códigos o una passkey."""
    return has_totp(conn, user) or repo.passkey_count(conn, user["id"]) > 0


def status(conn: Connection, user) -> dict:
    """Lo que necesitan el perfil y la administración, y nada más: nunca la semilla, ni cifrada."""
    row = repo.factor(conn, user["id"])
    totp_on = bool(row and row["confirmed"])
    keys = [{"id": k["id"], "name": k["name"], "created_at": k["created_at"], "last_used_at": k["last_used_at"]}
            for k in repo.passkeys(conn, user["id"])]
    active = totp_on or bool(keys)
    return {"enrolled": active, "totp": totp_on, "pending": bool(row and not row["confirmed"]),
            "since": row["updated_at"] if totp_on else "", "passkeys": keys,
            "recovery_left": repo.recovery_left(conn, user["id"]) if active else 0}


# --------------------------------------------------------------------------- alta de la app de códigos

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


def enroll_confirm(conn: Connection, key: bytes | None, user, code: str, *,
                   now: float | None = None) -> list[str] | None:
    """Comprueba un alta pendiente con un código de la aplicación y la activa. Devuelve los códigos de recuperación
    nuevos en claro (la única vez que existen como texto), ``[]`` si la cuenta ya los tenía (de sus passkeys: se
    conservan) o ``None`` si el código no vale.

    El paso que la comprobó queda gastado: si no, lo primero que haría el factor nuevo sería aceptar otra vez el
    código que lo creó. Los códigos se generan aquí y no al empezar: un alta abandonada dejaría un juego funcionando.
    """
    row = repo.factor(conn, user["id"])
    if not row or row["confirmed"]:
        return None
    try:
        secret = secretbox.decrypt(key, row["secret"])
    except secretbox.SecretError:
        return None
    first = not enrolled(conn, user)
    step = totp.verify(secret, code, now=now, after_step=row["last_step"])
    if step is None or not repo.confirm(conn, user["id"], step):
        return None
    return _new_recovery(conn, user) if first else []


# --------------------------------------------------------------------------- comprobar un código

def verify(conn: Connection, key: bytes | None, user, code: str, *, now: float | None = None) -> str:
    """``"totp"``, ``"recovery"`` o ``""``: qué fue el código, si fue algo.

    Primero como TOTP y solo después como código de recuperación, para que seis dígitos nunca gasten uno. Los dos
    caminos gastan lo que usan, y de forma atómica (``note_step``, ``consume_recovery``). Los códigos de recuperación
    valen también en una cuenta que solo tiene passkeys (para el día que se pierde la llave).
    """
    if not enrolled(conn, user):
        return ""
    row = repo.factor(conn, user["id"])
    secret = ""
    if row and row["confirmed"]:
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


# --------------------------------------------------------------------------- passkeys

class PasskeyError(Exception):
    """La passkey no vale. ``reason`` va a la auditoría; a quien la mandó solo se le dice que no vale."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def passkey_scope(cfg: dict) -> tuple[str, str]:
    """``(rp_id, origen)`` de las passkeys, o ``("", "")`` si este servidor no puede ofrecerlas: desactivadas
    (``security.passkeys``) o sin una dirección pública con nombre y HTTPS (``network.public_url``)."""
    if not cfg["security"].get("passkeys", True):
        return "", ""
    return webauthn.scope_from(cfg["network"].get("public_url", ""))


def new_challenge() -> str:
    return webauthn.new_challenge()


# Challenges ya gastados, hasta que caducan. El challenge viaja en la cookie firmada, y la cookie es del cliente:
# quitarlo de ella («session.pop») no impide reenviar la cookie de antes con la misma respuesta. Con un contador de
# firmas el reenvío se notaría, pero los autenticadores de plataforma no llevan (siempre 0), así que el único
# «una sola vez» que vale es este, del lado del servidor. En memoria del proceso, como los códigos de /connect:
# Waitress es un proceso y un challenge vive 5 minutos.
_SPENT: dict[str, float] = {}
_SPENT_LOCK = threading.Lock()


def spend_challenge(challenge: str, expires_at: float) -> bool:
    """Gasta un challenge emitido por este servidor: ``True`` la primera vez, ``False`` si ya se usó."""
    if not challenge:
        return False
    now = time.time()
    with _SPENT_LOCK:
        for old in [c for c, exp in _SPENT.items() if exp < now]:
            del _SPENT[old]
        if challenge in _SPENT:
            return False
        _SPENT[challenge] = max(float(expires_at or 0), now)
        return True


def _user_handle(uid) -> str:
    """El ``user.id`` de las passkeys de una cuenta: su uid (no el nombre: un cambio de nombre no puede soltarlas)."""
    return webauthn.b64u_encode(str(uid).encode())


def registration_options(conn: Connection, user, *, rp_id: str, rp_name: str, challenge: str,
                         resident: bool = False) -> dict:
    """Lo que necesita ``navigator.credentials.create()``. ``exclude`` evita registrar dos veces el mismo
    autenticador. ``resident`` (entrar sin contraseña encendido): pedir que la passkey se guarde en el dispositivo
    (credencial residente), que es lo que deja al navegador ofrecerla sin escribir el usuario; si no, se desaconseja
    (las llaves de seguridad tienen pocos huecos)."""
    return {"challenge": challenge, "rp": {"id": rp_id, "name": rp_name},
            "user": {"id": _user_handle(user["uid"]), "name": user["username"],
                     "displayName": user["display_name"] or user["username"]},
            "algorithms": list(cose.SUPPORTED), "timeout": CHALLENGE_SECONDS * 1000,
            "exclude": [k["credential_id"] for k in repo.passkeys(conn, user["id"])],
            "residentKey": "preferred" if resident else "discouraged"}


def register_passkey(conn: Connection, user, *, attestation_object: bytes, client_data_json: bytes, challenge: str,
                     rp_id: str, origin: str, name: str) -> list[str]:
    """Verifica un registro y guarda la passkey (sin paso de confirmación: la ceremonia firmada sobre un challenge de
    este servidor ES la prueba). Devuelve los códigos de recuperación nuevos si es el primer factor de la cuenta,
    ``[]`` si ya los tenía, o lanza :class:`PasskeyError`."""
    try:
        cred = webauthn.verify_registration(attestation_object=attestation_object, client_data_json=client_data_json,
                                            challenge=challenge, rp_id=rp_id, origin=origin)
    except webauthn.CeremonyError as exc:
        raise PasskeyError(str(exc)) from exc
    credential_id = webauthn.b64u_encode(cred["credential_id"])
    if repo.credential_taken(conn, credential_id):
        raise PasskeyError("credential already registered")
    label = clean_name(name) or "Passkey"
    first = not enrolled(conn, user)
    try:
        repo.add_passkey(conn, user["id"], credential_id=credential_id,
                         public_key=webauthn.b64u_encode(cred["public_key_raw"]), alg=cred["alg"],
                         sign_count=cred["sign_count"], name=label, aaguid=cred["aaguid"].hex())
    except sqlite3.IntegrityError as exc:
        # Dos registros de la misma credencial a la vez (doble clic, dos pestañas): los dos pasaron
        # credential_taken y el UNIQUE decide. El segundo es un rechazo como cualquier otro, no un 500
        conn.rollback()
        raise PasskeyError("credential already registered") from exc
    return _new_recovery(conn, user) if first else []


def assertion_options(conn: Connection, user, *, rp_id: str, challenge: str) -> dict:
    """Lo que necesita ``navigator.credentials.get()``: solo las passkeys de ESTA cuenta."""
    return {"challenge": challenge, "rpId": rp_id, "timeout": CHALLENGE_SECONDS * 1000,
            "allow": [k["credential_id"] for k in repo.passkeys(conn, user["id"])]}


def _check_assertion(conn: Connection, row, *, auth_data: bytes, client_data_json: bytes, signature: bytes,
                     challenge: str, rp_id: str, origin: str, require_uv: bool = False) -> None:
    """Comprueba la firma de una aserción con la passkey ``row`` (su clave, su algoritmo y su contador) y apunta su
    uso; :class:`PasskeyError` si no vale o si otra petición la usó a la vez."""
    try:
        key = cbor.decode(webauthn.b64u_decode(row["public_key"]))
        out = webauthn.verify_assertion(auth_data=auth_data, client_data_json=client_data_json, signature=signature,
                                        challenge=challenge, rp_id=rp_id, origin=origin, public_key=key,
                                        alg=row["alg"], last_sign_count=row["sign_count"], require_uv=require_uv)
    except (webauthn.CeremonyError, cbor.CborError) as exc:
        raise PasskeyError(str(exc)) from exc
    if not repo.note_passkey_use(conn, row["id"], row["sign_count"], out["sign_count"]):
        raise PasskeyError("concurrent use of the same credential")


def verify_passkey(conn: Connection, user, *, credential_id: str, auth_data: bytes, client_data_json: bytes,
                   signature: bytes, challenge: str, rp_id: str, origin: str) -> str:
    """Comprueba una aserción con una passkey de esta cuenta y apunta su uso. Devuelve su nombre o lanza
    :class:`PasskeyError`."""
    row = repo.passkey(conn, user["id"], str(credential_id or ""))
    if row is None:
        raise PasskeyError("unknown credential")
    _check_assertion(conn, row, auth_data=auth_data, client_data_json=client_data_json, signature=signature,
                     challenge=challenge, rp_id=rp_id, origin=origin)
    return row["name"]


# --------------------------------------------------------------------------- entrar solo con una passkey

def passwordless_on(cfg: dict) -> bool:
    """Si este servidor ofrece entrar solo con una passkey: ``security.passkey_login`` y passkeys disponibles."""
    return bool(cfg["security"].get("passkey_login")) and bool(passkey_scope(cfg)[0])


def passwordless_allowed(cfg: dict, user) -> bool:
    """Si ESTA cuenta puede entrar solo con su passkey: activa, de un método con contraseña encendido que la guarda
    aquí (las locales). En las demás (PAM) el sistema decide si la cuenta sigue valiendo, y eso solo se sabe
    comprobando su contraseña: una passkey no puede saltárselo."""
    method = providers.get(user["source"])
    return (bool(user["enabled"]) and method is not None and method.password and method.stores_password
            and not method.sso and method.enabled(cfg))


def passwordless_options(*, rp_id: str, challenge: str) -> dict:
    """``navigator.credentials.get()`` sin cuenta: lista vacía (el navegador ofrece las passkeys guardadas para este
    sitio) y verificación de la persona obligatoria (PIN, huella o cara), porque vale por los dos pasos."""
    return {"challenge": challenge, "rpId": rp_id, "timeout": CHALLENGE_SECONDS * 1000, "allow": [],
            "userVerification": "required"}


def passkey_owner(conn: Connection, credential_id: str) -> int | None:
    """El id de la cuenta de esa passkey, o ``None`` (para contar los fallos en ella antes de comprobarla)."""
    row = repo.passkey_by_credential(conn, str(credential_id or ""))
    return row["user_id"] if row is not None else None


def verify_passwordless(conn: Connection, *, credential_id: str, user_handle: bytes, auth_data: bytes,
                        client_data_json: bytes, signature: bytes, challenge: str, rp_id: str, origin: str) -> int:
    """Comprueba una aserción sin cuenta previa y apunta su uso. Devuelve el id de la cuenta dueña de la passkey o
    lanza :class:`PasskeyError`. Además de lo de siempre: el ``userHandle`` que devuelve el autenticador tiene que ser
    el de esa cuenta (WebAuthn §7.2, paso 6) y la persona tiene que haberse verificado (flag UV)."""
    row = repo.passkey_by_credential(conn, str(credential_id or ""))
    if row is None:
        raise PasskeyError("unknown credential")
    # Los bytes que se dieron como user.id al registrarla (los de _user_handle, ya decodificados): el uid de la cuenta
    if not user_handle or bytes(user_handle) != str(row["user_uid"]).encode():
        raise PasskeyError("user handle does not match")
    _check_assertion(conn, row, auth_data=auth_data, client_data_json=client_data_json, signature=signature,
                     challenge=challenge, rp_id=rp_id, origin=origin, require_uv=True)
    return row["user_id"]


def clean_name(name: str) -> str:
    return " ".join(str(name or "").split())[:PASSKEY_NAME_MAX]


def passkey_name(conn: Connection, user, passkey_id: int) -> str:
    """El nombre de una passkey de esta cuenta, o ``""`` si no es suya."""
    for k in repo.passkeys(conn, user["id"]):
        if k["id"] == passkey_id:
            return k["name"]
    return ""


def remove_passkey(conn: Connection, user, passkey_id: int) -> bool:
    return repo.remove_passkey(conn, user["id"], int(passkey_id))


def rename_passkey(conn: Connection, user, passkey_id: int, name: str) -> bool:
    label = clean_name(name)
    return bool(label) and repo.rename_passkey(conn, user["id"], int(passkey_id), label)


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
    """Quita TODO el segundo paso (app, passkeys y códigos): el reinicio del administrador y ``mfa-reset``. Devuelve
    si había algo. (Las semillas se vuelven a cifrar con otra clave en ``settings.secretbox.rekey``.)"""
    return repo.delete(conn, user["id"])


def remove_totp(conn: Connection, user) -> bool:
    """Quita solo la app de códigos (las passkeys siguen; los códigos de recuperación, si queda alguna)."""
    return repo.delete_totp(conn, user["id"])

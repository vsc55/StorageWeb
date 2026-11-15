"""Cifrado de los secretos de los ajustes (AES-256-GCM).

Los secretos (``SECRET_FIELDS``: el ``client_secret`` de Entra ID, el token de las métricas… y las opciones
``secret`` de cada ubicación remota) se guardan en la tabla ``settings`` cifrados, como ``enc:v1:<base64>``.
Quien se lleve solo la base de datos (o una copia de ella) no los puede leer.

La clave (32 bytes, en base64url) es, por orden: la variable ``STORAGEWEB_SECRETS_KEY`` o el fichero
``<data_dir>/secrets.key`` (``0600``), que se genera la primera vez. Es independiente de la ``secret_key`` de las
sesiones. Las copias de seguridad la incluyen; al restaurar una copia de otro servidor, sus secretos se vuelven a
cifrar con la clave de este (:func:`rekey`).

En ``config.json`` o en el entorno también se puede poner un secreto cifrado (``storageweb encrypt-secret``); lo
que no empiece por ``enc:v1:`` se usa tal cual. Contraseñas y tokens de API no pasan por aquí: de ellos solo se
guarda el hash.
"""
from __future__ import annotations

import base64
import binascii
import copy
import logging
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from sqlite3 import Connection

from ..i18n import _
from . import location_types
from .defaults import SECRET_FIELDS
from .errors import ConfigError
from .layers import _get, _set

PREFIX = "enc:v1:"
KEY_FILE = "secrets.key"
ENV = "STORAGEWEB_SECRETS_KEY"
_NONCE = 12
_AAD = b"storageweb-settings"
_log = logging.getLogger(__name__)


class SecretError(Exception):
    pass


# --------------------------------------------------------------------------- la clave

def generate_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def parse_key(text: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
    except (binascii.Error, ValueError) as exc:
        raise SecretError(_("The secrets key is not valid base64.")) from exc
    if len(key) != 32:
        raise SecretError(_("The secrets key must be 32 bytes (44 base64 characters)."))
    return key


def key_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / KEY_FILE


def load_key(data_dir: str | Path, environ=None, create: bool = True) -> bytes | None:
    """La clave: de ``STORAGEWEB_SECRETS_KEY`` o de ``<data_dir>/secrets.key`` (que se crea si falta y
    ``create``). ``None`` si no hay ninguna y no se crea."""
    environ = os.environ if environ is None else environ
    if environ.get(ENV):
        return parse_key(environ[ENV])
    path = key_path(data_dir)
    if path.exists():
        return parse_key(path.read_text(encoding="utf-8"))
    if not create:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    text = generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return parse_key(text)


def write_key(data_dir: str | Path, text: str) -> None:
    """Sustituye el fichero de la clave (al rotarla o al restaurar una copia en un servidor nuevo)."""
    parse_key(text)
    path = key_path(data_dir)
    tmp = path.with_name(f".{KEY_FILE}.nuevo")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text.strip())
    os.replace(tmp, path)


# --------------------------------------------------------------------------- un valor

def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(key: bytes, plain: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415 (solo al usarlo)
    nonce = secrets.token_bytes(_NONCE)
    sealed = AESGCM(key).encrypt(nonce, plain.encode("utf-8"), _AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")


def decrypt(key: bytes | None, value: str) -> str:
    """El valor en claro. Lo que no está cifrado se devuelve tal cual (un secreto escrito en claro en config.json o
    en el entorno)."""
    if not is_encrypted(value):
        return value
    if key is None:
        raise SecretError(_("A secret is encrypted but there is no secrets key (%(file)s or %(env)s).",
                            file=KEY_FILE, env=ENV))
    from cryptography.exceptions import InvalidTag  # noqa: PLC0415
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415
    try:
        raw = base64.urlsafe_b64decode(value[len(PREFIX):])
        return AESGCM(key).decrypt(raw[:_NONCE], raw[_NONCE:], _AAD).decode("utf-8")
    except (InvalidTag, binascii.Error, ValueError) as exc:
        raise SecretError(_("A secret cannot be decrypted with this secrets key (was it changed?).")) from exc


# --------------------------------------------------------------------------- un documento de ajustes

def _map(doc: dict, fn: Callable[[str], str]) -> dict:
    """Copia de ``doc`` con ``fn`` aplicada a cada secreto no vacío (campos y opciones de ubicaciones)."""
    out = copy.deepcopy(doc)
    for path in SECRET_FIELDS:
        value = _get(out, path)
        if isinstance(value, str) and value:
            _set(out, path, fn(value))
    for loc in (out.get("storage") or {}).get("locations") or []:
        if not isinstance(loc, dict):
            continue
        schema = location_types.get(loc.get("type", ""))
        for name in schema.secrets if schema else ():
            if isinstance(loc.get(name), str) and loc[name]:
                loc[name] = fn(loc[name])
    return out


def encrypt_doc(key: bytes, doc: dict) -> dict:
    return _map(doc, lambda v: v if is_encrypted(v) else encrypt(key, v))


def decrypt_doc(key: bytes | None, doc: dict, lenient: bool = False) -> dict:
    """Con ``lenient``, un secreto que no se puede descifrar queda vacío (y se avisa en el registro): el servicio
    sigue funcionando y basta con volver a escribirlo en la web."""
    def open_one(value: str) -> str:
        try:
            return decrypt(key, value)
        except SecretError:
            if not lenient:
                raise
            _log.error("A stored secret cannot be decrypted with the secrets key: it is ignored until saved again")
            return ""
    return _map(doc, open_one)


def decrypt_layer(key: bytes | None, doc: dict, where: str) -> dict:
    """Descifra los secretos de config.json o del entorno; :class:`ConfigError` si no se puede."""
    try:
        return decrypt_doc(key, doc)
    except SecretError as exc:
        raise ConfigError(f"{where}: {exc}") from exc


# --------------------------------------------------------------------------- la base de datos

def _locations(conn: Connection, profile: str, fn: Callable[[str], str]) -> int:
    """Aplica ``fn`` a los secretos de las ubicaciones guardadas del perfil (tabla ``location_options``) y
    guarda las que cambian. Devuelve cuántas."""
    from ..db.repositories import catalog  # noqa: PLC0415
    changed = 0
    for position, loc in enumerate(catalog.list_locations(conn, profile)):
        sealed = _map({"storage": {"locations": [loc]}}, fn)["storage"]["locations"][0]
        if sealed != loc:
            catalog.save_location(conn, profile, sealed, position, "system")
            changed += 1
    conn.commit()
    return changed


def rekey(conn: Connection, old: bytes | None, new: bytes) -> int:
    """Vuelve a cifrar los secretos guardados (ajustes y ubicaciones) de la clave ``old`` a ``new`` (rotación, o una
    copia restaurada de otro servidor). Lo que esté en claro también queda cifrado. Un secreto que no se pueda
    descifrar con ``old`` se deja como está (y se avisa en el registro)."""
    from . import store  # noqa: PLC0415
    changed = 0
    for name in store.profile_names(conn):
        def convert(value: str, name=name) -> str:
            if not is_encrypted(value):
                return encrypt(new, value)
            try:
                return encrypt(new, decrypt(old, value))
            except SecretError:
                try:
                    decrypt(new, value)  # ya estaba con la clave nueva
                except SecretError:
                    _log.warning("A secret in %s cannot be decrypted with either key: it is kept as is", name)
                return value
        doc = store.read_doc(conn, name)
        sealed = _map(doc, convert)
        if sealed != doc:
            store.put_doc(conn, name, sealed, "system")
            changed += 1
        changed += _locations(conn, name, convert)
    return changed

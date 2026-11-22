"""Verificación en dos pasos en los tests: dar de alta la app (TOTP) como desde el perfil, sus códigos, y registrar
passkeys como el navegador (con las ceremonias de tests/webauthn_fabric.py)."""
from __future__ import annotations

from tests.helpers import get_csrf


def secrets_key(app):
    """La clave con la que la aplicación cifra los secretos (y las semillas TOTP)."""
    return app.extensions["storageweb.runtime"].secrets_key


def code(secret: str, offset: int = 0) -> str:
    """El código TOTP de ``secret`` en el paso actual (más ``offset``)."""
    from storageweb.core.mfa import totp
    return totp.code_at(secret, totp.current_step() + offset)


def enrol(app, username: str) -> tuple[str, list[str]]:
    """Activa la verificación de ``username`` como desde su perfil. Devuelve la semilla y los códigos de recuperación.
    El código del alta gasta el paso actual: los siguientes inicios de sesión usan ``code(secret, 1)``."""
    from storageweb.core import mfa
    from storageweb.db.repositories import users
    from storageweb.web.context import get_db
    with app.app_context():
        user = users.get_by_username(get_db(), username)
        setup = mfa.enroll_begin(get_db(), secrets_key(app), user, "StorageWeb")
        codes = mfa.enroll_confirm(get_db(), secrets_key(app), user, code(setup["secret"]))
    assert len(codes) == 10
    return setup["secret"], codes


def submit(client, url: str, value: str):
    """Envía un código al formulario de ``url`` (con el token CSRF de esa página)."""
    return client.post(url, data={"_csrf": get_csrf(client, url), "code": value})


def post_json(client, url: str, body: dict, token: str):
    return client.post(url, json=body, headers={"X-CSRF-Token": token})


def register(client, token: str, *, name: str = "Portátil", cred_id: bytes = b"cred-0001", count: int = 1,
             options="/profile/mfa/passkey/options", verify="/profile/mfa/passkey/register"):
    """Registra una passkey como el navegador. Devuelve ``(clave privada, respuesta)``."""
    from storageweb.core.mfa import webauthn as wa
    from tests.webauthn_fabric import _registration
    opts = post_json(client, options, {"for": "register"}, token)
    assert opts.status_code == 200, opts.get_json()
    challenge = opts.get_json()["challenge"]
    priv, _key, att, cdj = _registration(challenge, cred_id=cred_id, count=count)
    resp = post_json(client, verify, {"attestation_object": wa.b64u_encode(att),
                                      "client_data_json": wa.b64u_encode(cdj), "name": name}, token)
    return priv, resp

"""Comandos de los secretos cifrados de los ajustes (``settings.secretbox``)."""
from __future__ import annotations

import getpass
import os
import sys

from ..db.repositories import audit
from ..i18n import _, _l
from ..settings import secretbox
from .common import command


def _encrypt_args(p):
    p.add_argument("--value", help=_("The secret (if missing, it is asked without showing it)"))


@command("encrypt-secret", _l("Encrypt a secret to put it in config.json or in an environment variable"),
         _encrypt_args, order=150)
def cmd_encrypt_secret(cfg, conn, args):
    """Para no dejar el ``client_secret`` o la contraseña de una ubicación en claro en config.json: se pone el
    resultado (``enc:v1:…``) en su lugar y el servicio lo descifra con su clave al arrancar."""
    value = args.value if args.value is not None else getpass.getpass(_("Secret: "))
    if not value:
        sys.exit(_("Nothing to encrypt."))
    key = secretbox.load_key(cfg["data_dir"])
    print(secretbox.encrypt(key, value))


@command("rotate-secrets-key", _l("Create a new key for the stored secrets and encrypt them again (service stopped)"),
         order=151)
def cmd_rotate_secrets_key(cfg, conn, args):
    """Si la clave se ha podido filtrar. Con el servicio parado: el que está en marcha tiene la clave en memoria.
    Los secretos de config.json cifrados con la clave antigua hay que volver a cifrarlos (``encrypt-secret``)."""
    from_env = bool(os.environ.get(secretbox.ENV))
    old = secretbox.load_key(cfg["data_dir"], create=False)
    text = secretbox.generate_key()
    changed = secretbox.rekey(conn, old, secretbox.parse_key(text))
    audit.log(conn, "secrets_key_rotated", username="cli", detail=str(changed))
    if from_env:
        # La clave la pone el entorno: no se guarda en ningún fichero, la cambia quien la puso
        print(_("%(count)s settings re-encrypted with a new key. Put it in %(env)s before starting the service:",
                count=changed, env=secretbox.ENV))
        print(text)
    else:
        secretbox.write_key(cfg["data_dir"], text)
        print(_("New key saved in %(path)s; %(count)s settings re-encrypted. Start the service again.",
                path=secretbox.key_path(cfg["data_dir"]), count=changed))
    print(_("Secrets encrypted in config.json with the old key must be encrypted again with encrypt-secret."))

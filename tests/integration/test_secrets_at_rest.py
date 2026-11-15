"""Secretos cifrados en la base de datos (``settings.secretbox``): web, arranque, config.json, copias y CLI."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from storageweb import create_app
from storageweb.core import backup, maintenance
from storageweb.settings import load_config, secretbox
from storageweb.web.context import boot_config, settings
from tests.helpers import add_user, get_csrf, login, store_settings, stored_settings

TOKEN = "prometheus-token-1234567890"
ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- el cifrado en sí

def test_encrypt_decrypt_and_documents():
    key, other = secretbox.parse_key(secretbox.generate_key()), secretbox.parse_key(secretbox.generate_key())
    sealed = secretbox.encrypt(key, "s3cr3to")
    assert sealed.startswith("enc:v1:") and "s3cr3to" not in sealed
    assert secretbox.encrypt(key, "s3cr3to") != sealed                       # nonce distinto cada vez
    assert secretbox.decrypt(key, sealed) == "s3cr3to"
    assert secretbox.decrypt(key, "en claro") == "en claro"                  # los de antes del cifrado
    with pytest.raises(secretbox.SecretError):
        secretbox.decrypt(other, sealed)
    with pytest.raises(secretbox.SecretError):
        secretbox.decrypt(None, sealed)
    with pytest.raises(secretbox.SecretError):
        secretbox.parse_key("corta")
    doc = {"app_name": "X", "auth": {"entra": {"client_secret": "abc", "client_id": "c1"}},
           "metrics": {"token": TOKEN},
           "storage": {"locations": [{"name": "nas", "type": "smb", "host": "nas", "share": "d", "username": "u",
                                      "password": "clave-smb"}]}}
    sealed_doc = secretbox.encrypt_doc(key, doc)
    assert sealed_doc["auth"]["entra"]["client_id"] == "c1" and sealed_doc["app_name"] == "X"
    for value in (sealed_doc["auth"]["entra"]["client_secret"], sealed_doc["metrics"]["token"],
                  sealed_doc["storage"]["locations"][0]["password"]):
        assert value.startswith("enc:v1:")
    assert sealed_doc["storage"]["locations"][0]["username"] == "u"
    assert secretbox.decrypt_doc(key, sealed_doc) == doc
    assert secretbox.decrypt_doc(other, sealed_doc, lenient=True)["metrics"]["token"] == ""   # no rompe nada


def test_key_from_file_or_environment(tmp_path):
    key = secretbox.load_key(tmp_path)
    path = tmp_path / "secrets.key"
    assert path.exists() and secretbox.load_key(tmp_path) == key            # se crea una vez
    if os.name != "nt":
        assert oct(path.stat().st_mode & 0o777) == "0o600"
    env_key = secretbox.generate_key()
    assert secretbox.load_key(tmp_path, {secretbox.ENV: env_key}) == secretbox.parse_key(env_key)
    assert secretbox.load_key(tmp_path / "otro", {}, create=False) is None


# --------------------------------------------------------------------------- en la aplicación

def _raw(app):
    return stored_settings(app)


def test_secrets_saved_from_the_web_are_encrypted(make_app):
    app = make_app()
    add_user(app, "root", role="admin")
    admin = app.test_client()
    login(admin, "root")
    form = {"_csrf": get_csrf(admin, "/admin/settings/maintenance"), "audit_retention_days": "0",
            "backup_interval_hours": "0", "backup_keep": "7", "metrics_enabled": "on", "metrics_token": TOKEN,
            "metrics_allowed_networks": ""}
    admin.post("/admin/settings/maintenance", data=form)
    stored = _raw(app)["metrics"]["token"]
    assert stored.startswith("enc:v1:") and TOKEN not in json.dumps(_raw(app))
    with app.app_context():
        assert settings()["metrics"]["token"] == TOKEN                     # la aplicación lo ve en claro
    assert admin.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    admin.post("/admin/settings/maintenance", data={**form, "metrics_token": ""})   # vacío = se conserva
    with app.app_context():
        assert settings()["metrics"]["token"] == TOKEN


def test_encrypted_secret_in_config_json(write_config, tmp_path):
    path = write_config()
    key = secretbox.load_key(tmp_path / "data")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["metrics"] = {"enabled": True, "token": secretbox.encrypt(key, TOKEN)}
    path.write_text(json.dumps(cfg), encoding="utf-8")
    assert load_config(path, environ={})["metrics"]["token"] == TOKEN       # la CLI
    app = create_app(str(path))
    with app.app_context():
        assert settings()["metrics"]["token"] == TOKEN                     # y el servicio
    (tmp_path / "data" / "secrets.key").write_text(secretbox.generate_key(), encoding="utf-8")
    with pytest.raises(Exception, match="config.json"):
        create_app(str(path))                                               # otra clave: error claro


def test_backup_carries_the_key_and_another_server_re_encrypts(make_app, tmp_path):
    first = make_app()
    add_user(first, "root", role="admin")
    admin = first.test_client()
    login(admin, "root")
    form = {"_csrf": get_csrf(admin, "/admin/settings/maintenance"), "audit_retention_days": "0",
            "backup_interval_hours": "0", "backup_keep": "7", "metrics_enabled": "on", "metrics_token": TOKEN,
            "metrics_allowed_networks": ""}
    admin.post("/admin/settings/maintenance", data=form)
    with first.app_context():
        archive = maintenance.create_backup({**boot_config(), "maintenance": settings()["maintenance"]})
    import tarfile
    with tarfile.open(archive) as tar:
        assert "secrets.key" in tar.getnames()

    other_dir = tmp_path / "otro"
    other_dir.mkdir()
    (other_dir / "config.json").write_text(json.dumps({"data_dir": "data", "default_locale": "es",
                                                       "session": {"cookie_secure": False}}), encoding="utf-8")
    second = create_app(str(other_dir / "config.json"))                     # otro servidor, con su propia clave
    with second.app_context():
        backup.restore_online(boot_config(), archive)
        second.extensions["storageweb.runtime"]._rev = None
        assert settings()["metrics"]["token"] == TOKEN                     # se lee con la clave de este
    assert secretbox.load_key(other_dir / "data") != secretbox.load_key(tmp_path / "data")


def test_cli_encrypt_and_rotate(write_config, tmp_path, make_app):
    path = write_config()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "STORAGEWEB_LANG": "es",
           "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "src"), os.environ.get("PYTHONPATH")]))}
    env.pop(secretbox.ENV, None)

    def cli(*args):
        res = subprocess.run([sys.executable, "-m", "storageweb", "--config", str(path), *args],
                             capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env)
        assert res.returncode == 0, res.stderr
        return res.stdout

    sealed = cli("encrypt-secret", "--value", "clave-de-ubicacion").strip().splitlines()[-1]
    key = secretbox.load_key(tmp_path / "data")
    assert secretbox.decrypt(key, sealed) == "clave-de-ubicacion"
    app = create_app(str(path))
    store_settings(app, secretbox.encrypt_doc(key, {"metrics": {"token": TOKEN}}))
    out = cli("rotate-secrets-key")
    assert "1" in out and "encrypt-secret" in out
    new_key = secretbox.load_key(tmp_path / "data")
    assert new_key != key
    stored = stored_settings(app)["metrics"]["token"]
    assert secretbox.decrypt(new_key, stored) == TOKEN

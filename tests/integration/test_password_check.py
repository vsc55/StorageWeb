"""Contraseñas comunes (security.password_check): la regla, la lista que viaja con StorageWeb y los tres sitios donde
se pone una contraseña (alta y cambio del administrador, Mi perfil, la CLI)."""
from __future__ import annotations

import subprocess
import sys

import pytest

from storageweb.providers import local
from tests.helpers import PASSWORD, add_user, get_csrf, login
from tests.integration.test_cli import ENV, ROOT, cli  # noqa: F401 (el fixture)


@pytest.mark.parametrize("password, why", [
    ("1234567890", "más comunes"), ("Password123", "más comunes"), ("QWERTYUIOP", "más comunes"),
    ("contraseña", "más comunes"), ("aaaaaaaaaaaa", "muy pocos"), ("abababababab", "muy pocos"),
    ("anabelen2020", "nombre de usuario"),
])
def test_rejected(password, why):
    with pytest.raises(ValueError, match=why):
        local.validate_password(password, username="AnaBelen2020")


def test_accepted_and_the_switch():
    local.validate_password(PASSWORD, username="ana")                      # la de los tests
    local.validate_password("caballo-grapa-bateria", username="ana")
    local.validate_password("1234567890", check_common=False)              # apagado: solo la longitud
    with pytest.raises(ValueError, match="al menos"):
        local.validate_password("corta", check_common=False)


def test_the_shipped_list():
    words = local.common_passwords()
    assert len(words) > 10_000 and all(len(w) >= local.MIN_PASSWORD_LENGTH and w == w.lower() for w in words)
    assert "password123" in words and not any(w.startswith("#") for w in words)
    res = subprocess.run([sys.executable, "tools/common_passwords.py", "--check"], cwd=ROOT, env=ENV,
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stdout                                 # nadie la tocó a mano


def test_admin_my_profile_and_the_switch(app, admin, make_app):
    client, token = admin
    page = client.post("/admin/users/new", data={"_csrf": token, "username": "luis", "password": "qwertyuiop",
                                                 "source": "local", "role": "user"}, follow_redirects=True)
    assert "de las más comunes" in page.get_data(as_text=True)
    page = client.post("/admin/users/new", data={"_csrf": token, "username": "luis", "password": "caballo-grapa-77",
                                                 "source": "local", "role": "user"}, follow_redirects=True)
    assert "creado" in page.get_data(as_text=True)

    add_user(app, "ana")
    ana = app.test_client()
    login(ana, "ana")
    t = get_csrf(ana, "/profile/security")
    page = ana.post("/profile/password", data={"_csrf": t, "current_password": PASSWORD, "new_password": "1q2w3e4r5t",
                                               "repeat_password": "1q2w3e4r5t"}, follow_redirects=True)
    assert "de las más comunes" in page.get_data(as_text=True)

    off = make_app({"security": {"password_check": False}})       # la misma base de datos: otra cuenta
    add_user(off, "eva")
    ana = off.test_client()
    login(ana, "eva")
    t = get_csrf(ana, "/profile/security")
    page = ana.post("/profile/password", data={"_csrf": t, "current_password": PASSWORD, "new_password": "1q2w3e4r5t",
                                               "repeat_password": "1q2w3e4r5t"}, follow_redirects=True)
    assert "Contraseña cambiada" in page.get_data(as_text=True)


def test_the_cli_follows_the_setting(cli, write_config):
    res = cli("user-add", "ana", "--password", "password123", ok=False)
    assert res.returncode != 0 and "más comunes" in res.stderr
    cli("user-add", "ana", "--password", "contraseña-larga")
    res = cli("user-passwd", "ana", "--password", "ana", ok=False)
    assert res.returncode != 0
    # Apagado en config.json: la CLI lo respeta
    cfg = write_config({"security": {"password_check": False}})
    res = subprocess.run([sys.executable, "-m", "storageweb", "--config", str(cfg), "user-passwd", "ana",
                          "--password", "password123"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
                         env=ENV)
    assert res.returncode == 0, res.stderr

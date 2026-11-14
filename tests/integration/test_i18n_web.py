"""Idioma de la interfaz web y de la CLI."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from storageweb.db.repositories import users
from storageweb.web.context import get_db
from tests.helpers import add_user, get_csrf, login

ROOT = Path(__file__).resolve().parents[2]
EN = {"Accept-Language": "en-US,en;q=0.9"}
SPANISH = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")


def _visible_text(html: str) -> str:
    """Texto de la página sin el catálogo JSON de JavaScript (que contiene ambos idiomas) ni los
    nombres de los idiomas, que se muestran siempre en su propio idioma («Español», «English»)."""
    html = re.sub(r'<script type="application/json" id="i18n-messages">.*?</script>', "", html, flags=re.S)
    return html.replace("Español", "")


def test_default_locale_is_english(tmp_path):
    """Sin configurar default_locale ni Accept-Language, la interfaz sale en inglés."""
    from storageweb import create_app

    cfg = tmp_path / "config.json"
    cfg.write_text('{"data_dir": "data", "session": {"cookie_secure": false}, "server": {"behind_proxy": false}}',
                   encoding="utf-8")
    html = create_app(str(cfg)).test_client().get("/login").get_data(as_text=True)
    assert '<html lang="en" ' in html and "Sign in" in html


def test_configured_spanish_default(client):
    html = client.get("/login").get_data(as_text=True)
    assert '<html lang="es" ' in html and "Iniciar sesión" in html


def test_accept_language_english(client):
    html = client.get("/login", headers=EN).get_data(as_text=True)
    assert '<html lang="en" ' in html and "Sign in" in html and "User name" in html
    assert not SPANISH.search(_visible_text(html))


def test_unsupported_language_uses_default(client):
    html = client.get("/login", headers={"Accept-Language": "fr-FR,fr"}).get_data(as_text=True)
    assert '<html lang="es" ' in html  # default_locale de los tests


def test_default_locale_setting(make_app):
    app = make_app({"default_locale": "en"})
    html = app.test_client().get("/login").get_data(as_text=True)
    assert '<html lang="en" ' in html


def test_invalid_default_locale(make_app):
    from storageweb.settings import ConfigError

    with pytest.raises(ConfigError, match="default_locale"):
        make_app({"default_locale": "fr"})


def test_switch_language_anonymous_survives_login(app, client):
    add_user(app, "ana")
    token = get_csrf(client)
    resp = client.post("/locale", data={"_csrf": token, "locale": "en", "next": "/login"})
    assert resp.status_code == 302 and resp.location == "/login"
    assert "Sign in" in client.get("/login").get_data(as_text=True)
    login(client, "ana")
    assert '<html lang="en" ' in client.get("/f/home/").get_data(as_text=True)


def test_switch_language_saved_for_user(app, logged):
    client, token = logged
    client.post("/locale", data={"_csrf": token, "locale": "en", "next": "/f/home/"})
    with app.app_context():
        assert users.get_by_username(get_db(), "ana")["locale"] == "en"
    # La preferencia guardada gana al navegador, también en otra sesión
    other = app.test_client()
    login(other, "ana")
    html = other.get("/f/home/", headers={"Accept-Language": "es"}).get_data(as_text=True)
    assert '<html lang="en" ' in html and "Upload files" in html


def test_switch_language_rejects_unknown(logged):
    client, token = logged
    client.post("/locale", data={"_csrf": token, "locale": "xx", "next": "/f/home/"})
    assert '<html lang="es" ' in client.get("/f/home/").get_data(as_text=True)


def test_switch_language_requires_csrf(client):
    assert client.post("/locale", data={"locale": "en"}).status_code == 400


def test_logout_keeps_language(logged):
    client, token = logged
    client.post("/locale", data={"_csrf": token, "locale": "en", "next": "/f/home/"})
    resp = client.post("/logout", data={"_csrf": get_csrf(client, "/f/home/")}, follow_redirects=True)
    assert "You have signed out." in resp.get_data(as_text=True)


@pytest.mark.parametrize("url", ["/f/home/", "/admin/users", "/admin/users/new", "/admin/settings/auth",
                                 "/admin/settings/system", "/admin/settings/entra/setup?step=3",
                                 "/admin/audit", "/f/no-existe/"])
def test_english_pages_have_no_spanish(admin, url):
    client, _ = admin
    html = client.get(url, headers=EN).get_data(as_text=True)
    leftovers = sorted({m.group(0) for m in re.finditer(r"[^<>\n]*[áéíóúñÁÉÍÓÚÑ¿¡][^<>\n]*", _visible_text(html))})
    assert not leftovers, leftovers


def test_spanish_page_has_translated_js_catalog(logged):
    client, _ = logged
    html = client.get("/f/home/").get_data(as_text=True)
    assert '"Are you sure?": "\\u00bfSeguro?"' in html or '"Are you sure?": "¿Seguro?"' in html


def test_flash_and_csrf_errors_translated(app, client):
    add_user(app, "ana")
    resp = client.post("/login", data={"username": "ana", "password": "x"}, headers=EN)
    assert resp.status_code == 400 and "Invalid CSRF token" in resp.get_data(as_text=True)
    token = get_csrf(client)
    resp = client.post("/login", data={"username": "ana", "password": "mala", "_csrf": token}, headers=EN)
    assert "Wrong user name or password." in resp.get_data(as_text=True)


def test_api_errors_translated(logged):
    client, token = logged
    headers = {"X-CSRF-Token": token, "Accept": "application/json"}
    resp = client.post("/api/uploads", json={"root": "no-existe", "name": "a", "size": 1}, headers={**headers, **EN})
    assert resp.status_code == 404 and resp.get_json()["error"] == "Folder not found"
    resp = client.post("/api/uploads", json={"root": "no-existe", "name": "a", "size": 1}, headers=headers)
    assert resp.get_json()["error"] == "Carpeta no encontrada"


def test_404_page_translated(logged):
    client, _ = logged
    html = client.get("/f/home/no/existe", headers=EN).get_data(as_text=True)
    assert "Not found" in html


def test_dates_follow_language(app, admin):
    client, _ = admin
    es = client.get("/admin/users").get_data(as_text=True)
    en = client.get("/admin/users", headers=EN).get_data(as_text=True)
    assert "Último acceso" in es and "Last sign-in" in en
    # root ha iniciado sesión: su fecha aparece con el formato de cada idioma
    assert re.search(r"\d{1,2}/\d{1,2}/\d{2}", es) and re.search(r"\d{1,2}/\d{1,2}/\d{2}", en)


# --------------------------------------------------------------------------- CLI

def _cli(lang, *args, cfg):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "STORAGEWEB_LANG": lang,
           "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "src"), os.environ.get("PYTHONPATH")]))}
    return subprocess.run([sys.executable, "-m", "storageweb", "--config", str(cfg), *args],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env)


def test_cli_english(write_config):
    cfg = write_config()
    out = _cli("en", "check-config", cfg=cfg).stdout
    assert "Valid configuration." in out and "WARNING: there is no administrator" in out
    assert "Start the web server" in _cli("en", "--help", cfg=cfg).stdout
    res = _cli("en", "user-add", "x", "--password", "corta", cfg=cfg)
    assert "at least 10 characters" in res.stderr


def test_cli_spanish(write_config):
    cfg = write_config()
    assert "Configuración válida." in _cli("es", "check-config", cfg=cfg).stdout
    assert "Arranca el servidor web" in _cli("es", "--help", cfg=cfg).stdout


def test_cli_user_locale(write_config):
    cfg = write_config()
    _cli("es", "user-add", "eva", "--password", "contraseña-larga", cfg=cfg)
    assert _cli("es", "user-set", "eva", "--locale", "en", cfg=cfg).returncode == 0
    from storageweb.db import connect
    from storageweb.settings import load_config

    conn = connect(load_config(cfg)["database"])
    assert users.get_by_username(conn, "eva")["locale"] == "en"
    conn.close()

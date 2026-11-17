"""Dirección pública, proxy inverso (incluidas cadenas de proxies y subrutas) y diagnóstico de HTTPS."""
import re

import pytest

from storageweb.settings import ConfigError, load_config
from tests.helpers import PASSWORD, add_user, get_csrf, login
from tests.sso_helpers import entra_cfg, start_login

PROXY = {"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "files.example.com"}


def _admin(app):
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    return client


@pytest.mark.parametrize("value, expected", [
    ("", ""), ("files.example.com", "https://files.example.com"),
    ("Files.Example.com/", "https://files.example.com"),
    ("files.example.com:8443/archivos/", "https://files.example.com:8443/archivos"),
    ("https://www.example.com/archivos/", "https://www.example.com/archivos"),
    ("http://localhost:8080", "http://localhost:8080"),
])
def test_public_url_normalized(tmp_path, value, expected):
    import json
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"network": {"public_url": value}}), encoding="utf-8")
    assert load_config(p)["network"]["public_url"] == expected


@pytest.mark.parametrize("value", ["files example.com", "ftp://x", "x/?a=1", "https://", "user@host.com",
                                   "-bad-.com"])
def test_public_url_invalid(tmp_path, value):
    import json
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"network": {"public_url": value}}), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    assert exc.value.field == "network.public_url"


@pytest.mark.parametrize("public, expected", [
    ("https://files.example.com", "https://files.example.com/auth/entra/callback"),
    ("https://www.example.com/archivos", "https://www.example.com/archivos/auth/entra/callback"),
])
def test_entra_redirect_uses_public_url(make_app, token_endpoint, public, expected):
    app = make_app({"network": {"public_url": public}, "auth": {"entra": entra_cfg()}})
    _, q = start_login(app.test_client(), token_endpoint)
    assert q["redirect_uri"] == expected


def test_without_public_url_uses_request_host(make_app, token_endpoint):
    app = make_app({"auth": {"entra": entra_cfg()}})
    _, q = start_login(app.test_client(), token_endpoint)
    assert q["redirect_uri"] == "http://localhost/auth/entra/callback"


def test_proxy_headers_prefix_and_hops(make_app):
    app = make_app({"server": {"behind_proxy": True, "proxy_hops": 2}})
    client = _admin(app)
    headers = {"X-Forwarded-For": "198.51.100.1, 10.0.0.2", "X-Forwarded-Proto": "https, https",
               "X-Forwarded-Host": "files.example.com, files.example.com", "X-Forwarded-Prefix": "/archivos, /archivos"}
    html = client.get("/admin/settings/network", headers=headers, base_url="https://localhost").get_data(as_text=True)
    assert "<code>https://files.example.com/archivos</code>" in html       # esquema, host y subruta del proxy
    assert "<code>198.51.100.1</code>" in html                              # IP real tras dos proxies
    assert 'href="/archivos/admin/users/"' in html                          # las URLs llevan la subruta


def test_network_section_save_and_validate(app):
    from storageweb.web.context import settings

    client = _admin(app)
    token = get_csrf(client, "/admin/settings/network")
    resp = client.post("/admin/settings/network", data={"_csrf": token, "public_url": "files example.com"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400 and 'class="field-error"' in html and "network.public_url" in html
    resp = client.post("/admin/settings/network", data={"_csrf": token, "public_url": "files.example.com"})
    assert resp.status_code == 302
    with app.test_request_context():
        assert settings()["network"]["public_url"] == "https://files.example.com"
    html = client.get("/admin/settings/network").get_data(as_text=True)
    assert "Estás entrando por localhost" in html and "server_name files.example.com;" in html
    assert 'name="public_url" value="files.example.com"' in html             # se muestra sin https://


def test_diagnostics_headers_ignored_without_behind_proxy(app):
    client = _admin(app)
    html = client.get("/admin/settings/network", headers=PROXY).get_data(as_text=True)
    assert "server.behind_proxy está desactivado" in html and "<code>203.0.113.7</code>" in html


def test_diagnostics_proxy_bypassed(make_app):
    app = make_app({"server": {"behind_proxy": True, "host": "0.0.0.0"}})
    client = _admin(app)
    html = client.get("/admin/settings/network").get_data(as_text=True)
    assert "no trae X-Forwarded-For" in html and "falsear" in html


def test_diagnostics_all_consistent(make_app):
    app = make_app({"server": {"behind_proxy": True}, "session": {"cookie_secure": True},
                    "network": {"public_url": "https://files.example.com"}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    # La cookie es solo HTTPS: el cliente de pruebas tiene que usar https y las cabeceras del proxy
    token_page = client.get("/login", base_url="https://files.example.com", headers=PROXY)
    assert token_page.status_code == 200
    csrf = re.search(r'name="_csrf" value="([^"]+)"', token_page.get_data(as_text=True)).group(1)
    client.post("/login", data={"_csrf": csrf, "username": "root", "password": PASSWORD},
                base_url="https://files.example.com", headers=PROXY)
    html = client.get("/admin/settings/network", base_url="https://files.example.com", headers=PROXY).get_data(as_text=True)
    assert "coinciden" in html and 'class="fail"' not in html


def test_apache_example_with_the_configured_values(make_app):
    """La página de red genera también el ejemplo de Apache con el nombre, la subruta y el tamaño máximo."""
    app = make_app({"network": {"public_url": "www.example.com/archivos"}, "server": {"max_upload_mb": 100}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    html = client.get("/admin/settings/network").get_data(as_text=True)
    assert "Ejemplo para Apache 2.4 con estos valores" in html
    assert "ServerName www.example.com" in html
    assert "ProxyPass        /archivos/ http://" in html and "nocanon" in html
    assert 'RequestHeader set X-Forwarded-Prefix "/archivos"' in html
    assert "LimitRequestBody " in html and "&lt;VirtualHost *:443&gt;" in html
    assert "RewriteRule ^ https://%{SERVER_NAME}%{REQUEST_URI} [R=301,L]" in html



def test_proxy_examples_never_pass_a_client_prefix(make_app):
    """Sin subruta, los ejemplos quitan la X-Forwarded-Prefix que pudiera mandar el cliente; con subruta, la ponen."""
    app = make_app({"network": {"public_url": "files.example.com"}})
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    html = client.get("/admin/settings/network").get_data(as_text=True)
    assert 'proxy_set_header X-Forwarded-Prefix "";' in html                  # nginx
    assert "RequestHeader unset X-Forwarded-Prefix" in html                    # Apache
    assert "header_up -X-Forwarded-Prefix" in html                             # Caddy
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in html and "SSLProtocol -all +TLSv1.2 +TLSv1.3" in html
    assert "server_tokens off;" in html and "ServerSignature Off" in html


def test_waitress_passes_the_proxy_headers_to_the_application(make_app):
    """Con un servidor Waitress de verdad: por defecto borra X-Forwarded-* que no vienen de un trusted_proxy, y
    entonces la aplicación veía todo como HTTP y desde la IP del proxy (auditoría, sesiones y bloqueo de IPs
    con la IP del proxy, que además nunca se bloquea por ser local). Detrás de un proxy no debe borrarlas."""
    import threading
    import urllib.error
    import urllib.request

    from waitress.server import create_server

    from storageweb.cli.server import waitress_options
    from storageweb.web.context import get_db

    app = make_app({"server": {"behind_proxy": True}})
    server = create_server(app, host="127.0.0.1", port=0, **waitress_options(app.config["SW"]["server"]))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{server.effective_port}/login", data=b"username=x",
                                     headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"})
        with pytest.raises(urllib.error.HTTPError) as err:   # sin token CSRF: 400 y cuenta como infracción
            urllib.request.urlopen(req, timeout=10)
        assert err.value.code == 400
    finally:
        server.close()
    with app.app_context():
        ips = [r["ip"] for r in get_db().execute("SELECT ip FROM ip_offenses")]
    assert ips == ["203.0.113.7"]                            # la del cliente, no la del proxy (127.0.0.1)
    assert waitress_options({**app.config["SW"]["server"], "behind_proxy": False})["clear_untrusted_proxy_headers"]

"""Generación del overlay de Gentoo y coherencia de las plantillas de empaquetado."""
import hashlib
import importlib.util
import re
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packaging"

_spec = importlib.util.spec_from_file_location("make_overlay", PKG / "gentoo" / "make_overlay.py")
make_overlay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_overlay)


@pytest.mark.parametrize("version, expected", [
    ("1.2.0", "1.2.0"),
    ("1.2.0-rc1", "1.2.0_rc1"),
    ("1.2.0-beta.2", "1.2.0_beta2"),
    ("2.0.0-alpha", "2.0.0_alpha"),
])
def test_gentoo_version(version, expected):
    assert make_overlay.gentoo_version(version) == expected


@pytest.mark.parametrize("version", ["1.2.0-dev", "v1.2.0", "1.2.0-rc1+build"])
def test_gentoo_version_invalid(version):
    with pytest.raises(ValueError):
        make_overlay.gentoo_version(version)


def test_overlay(tmp_path):
    tarball = tmp_path / "storageweb-1.4.0-rc2.tar.gz"
    tarball.write_bytes(b"contenido de prueba")
    out = make_overlay.build("1.4.0-rc2", "https://github.com/org/storageweb/", "all-rights-reserved",
                             tarball, tmp_path / "overlay.tar.gz")
    with tarfile.open(out) as tar:
        names = tar.getnames()
        ebuild = tar.extractfile("storageweb-overlay/www-apps/storageweb/storageweb-1.4.0_rc2.ebuild").read().decode()
        manifest = tar.extractfile("storageweb-overlay/www-apps/storageweb/Manifest").read().decode()
    for required in ("metadata/layout.conf", "profiles/repo_name", "acct-user/storageweb/storageweb-0.ebuild",
                     "acct-group/storageweb/storageweb-0.ebuild", "www-apps/storageweb/files/storageweb.initd",
                     "www-apps/storageweb/metadata.xml"):
        assert f"storageweb-overlay/{required}" in names
    assert not any(n.endswith((".in", ".py")) for n in names)
    assert not re.search(r"@[A-Z_]+@", ebuild.split("src_prepare")[0])  # sin marcadores en la cabecera
    assert 'SRC_URI="https://github.com/org/storageweb/releases/download/v1.4.0-rc2/storageweb-1.4.0-rc2.tar.gz"' in ebuild
    assert 'S="${WORKDIR}/storageweb-1.4.0-rc2"' in ebuild and 'LICENSE="all-rights-reserved"' in ebuild
    data = b"contenido de prueba"
    assert manifest == (f"DIST storageweb-1.4.0-rc2.tar.gz {len(data)} BLAKE2B {hashlib.blake2b(data).hexdigest()} "
                        f"SHA512 {hashlib.sha512(data).hexdigest()}\n")


def test_templates_use_known_placeholders():
    """Todas las plantillas usan solo marcadores que build.sh, install.sh y el ebuild sustituyen."""
    known = {"APP_USER", "APP_GROUP", "APP_DIR", "STORAGEWEB_BIN", "CONF_DIR", "DATA_DIR", "STORAGE_DIR"}
    for tpl in (*sorted((PKG / "systemd").glob("storageweb*")), PKG / "bin" / "storageweb-admin"):
        used = set(re.findall(r"@([A-Z_]+)@", tpl.read_text(encoding="utf-8")))
        assert used <= known, (tpl.name, used - known)
        for renderer in (PKG / "build.sh", PKG / "install.sh",
                         PKG / "gentoo" / "www-apps" / "storageweb" / "storageweb.ebuild.in"):
            text = renderer.read_text(encoding="utf-8")
            missing = {u for u in used if f"@{u}@" not in text}
            assert not missing, (renderer.name, tpl.name, missing)


def test_dockerfile_and_entrypoint():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER storageweb" in dockerfile and "HEALTHCHECK" in dockerfile and "/healthz" in dockerfile
    entry = (PKG / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "--password-stdin" in entry and 'exec storageweb "$@"' in entry


@pytest.mark.parametrize("template", ["nginx/storageweb.conf", "apache/storageweb.conf", "caddy/Caddyfile"])
def test_proxy_templates_are_shipped_everywhere(template):
    """Las plantillas de proxy (nginx, Apache y Caddy) van en los paquetes, en el ebuild de Gentoo y en install.sh."""
    assert (PKG / template).is_file()
    shipped = f"packaging/{template}"
    assert shipped in (PKG / "nfpm.yaml").read_text(encoding="utf-8")
    assert shipped in (PKG / "gentoo" / "www-apps" / "storageweb" / "storageweb.ebuild.in").read_text(encoding="utf-8")
    assert f'"$PKG/{template}"' in (PKG / "install.sh").read_text(encoding="utf-8")


def test_apache_template_essentials():
    """Lo que no puede faltar para subidas grandes, WebDAV y las URLs que genera la aplicación."""
    conf = (PKG / "apache" / "storageweb.conf").read_text(encoding="utf-8")
    for directive in ("LimitRequestBody", "ProxyPreserveHost On", "ProxyPass        / http://127.0.0.1:8080/ nocanon",
                      "AllowEncodedSlashes NoDecode", 'RequestHeader set X-Forwarded-Proto "https"',
                      "RequestReadTimeout", "ProxyTimeout 300",
                      "RewriteRule ^ https://%{SERVER_NAME}%{REQUEST_URI} [R=301,L]"):
        assert directive in conf, directive
    assert not any(line.strip().startswith("SetEnv proxy-sendchunked") for line in conf.splitlines())
    for directive in ("RequestHeader unset X-Forwarded-Prefix", "SSLProtocol -all +TLSv1.2 +TLSv1.3",
                      "ServerSignature Off", "ErrorLog", "CustomLog"):
        assert directive in conf, directive


def test_caddy_template_essentials():
    """Lo que Caddy no hace solo: tamaño máximo, quitar la subruta del cliente y no retener las descargas."""
    conf = (PKG / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    for directive in ("reverse_proxy 127.0.0.1:8080", "header_up -X-Forwarded-Prefix", "flush_interval -1",
                      "max_size", "tls internal"):
        assert directive in conf, directive


def test_caddy_compose_essentials():
    """compose.caddy.yaml: Caddy con el Caddyfile dentro, StorageWeb sin puerto publicado y detrás del proxy."""
    import yaml

    compose = yaml.safe_load((PKG / "docker" / "compose.caddy.yaml").read_text(encoding="utf-8"))
    caddy, app = compose["services"]["caddy"], compose["services"]["storageweb"]
    assert caddy["configs"] == [{"source": "caddyfile", "target": "/etc/caddy/Caddyfile"}]
    caddyfile = compose["configs"]["caddyfile"]["content"]
    for directive in ("${STORAGEWEB_DOMAIN} {", "reverse_proxy storageweb:8080", "header_up -X-Forwarded-Prefix",
                      "flush_interval -1", "max_size"):
        assert directive in caddyfile, directive
    assert caddyfile.count("{") == caddyfile.count("}")
    assert "ports" not in app and app["environment"]["STORAGEWEB_BEHIND_PROXY"] == "true"
    assert "caddy-data:/data" in caddy["volumes"]                # los certificados sobreviven
    assert app["image"] == "ghcr.io/vsc55/storageweb:latest" and "build" not in app   # sin el código


def test_traefik_compose_essentials():
    """compose.traefik.yaml: HTTPS con Traefik sin publicar StorageWeb, subidas grandes (readTimeout), nombres con
    caracteres codificados y la subruta del cliente quitada."""
    import yaml

    compose = yaml.safe_load((PKG / "docker" / "compose.traefik.yaml").read_text(encoding="utf-8"))
    traefik, app = compose["services"]["traefik"], compose["services"]["storageweb"]
    flags = set(traefik["command"])
    for flag in ("--providers.docker.exposedByDefault=false",
                 "--entryPoints.web.http.redirections.entryPoint.to=websecure",
                 "--entryPoints.websecure.transport.respondingTimeouts.readTimeout=0",
                 "--entryPoints.websecure.http.encodedCharacters.allowEncodedPercent=true",
                 "--entryPoints.websecure.http.encodedCharacters.allowEncodedHash=true",
                 "--entryPoints.websecure.http.encodedCharacters.allowEncodedQuestionMark=true"):
        assert flag in flags, flag
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in traefik["volumes"]
    assert "ports" not in app                                    # solo a través de Traefik
    assert app["environment"]["STORAGEWEB_BEHIND_PROXY"] == "true"
    labels = set(app["labels"])
    assert "traefik.http.middlewares.storageweb-noprefix.headers.customrequestheaders.X-Forwarded-Prefix=" in labels
    assert "traefik.http.routers.storageweb.middlewares=storageweb-noprefix" in labels
    assert "traefik.http.services.storageweb.loadbalancer.server.port=8080" in labels
    assert app["image"] == "ghcr.io/vsc55/storageweb:latest" and "build" not in app   # sin el código


def test_nginx_template_essentials():
    conf = (PKG / "nginx" / "storageweb.conf").read_text(encoding="utf-8")
    for directive in ('proxy_set_header X-Forwarded-Prefix "";', "ssl_protocols TLSv1.2 TLSv1.3;", "server_tokens off;",
                      "access_log", "error_log", "client_max_body_size", "proxy_request_buffering off",
                      "proxy_buffering off", "proxy_max_temp_file_size 0"):
        assert directive in conf, directive

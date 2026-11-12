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

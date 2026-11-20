"""tools/vendor.py --outdated: versión nueva (con al menos MIN_AGE_DAYS días) y avisos de seguridad de la fijada,
con un registro de npm falso (sin red)."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def vendor():
    spec = importlib.util.spec_from_file_location("vendor", Path(__file__).resolve().parents[2] / "tools" / "vendor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registry(vendor, latest: str, published: str, advisories=()):
    current = vendor.PACKAGES["mermaid"]["version"]

    def get_json(url, body=None):
        if url.endswith("/advisories/bulk"):
            if "mermaid" not in body:
                return {}
            assert body == {"mermaid": [current]}
            return {"mermaid": list(advisories)} if advisories else {}
        if not url.endswith("/mermaid"):        # las demás bibliotecas, al día
            other = next(p for n, p in vendor.PACKAGES.items() if url.endswith(p.get("registry", n).replace("/", "%2F")))
            return {"dist-tags": {"latest": other["version"]}, "time": {other["version"]: "2020-01-01T00:00:00Z"}}
        return {"dist-tags": {"latest": latest}, "time": {latest: published},
                "versions": {latest: {"dist": {"tarball": f"https://registry.npmjs.org/mermaid/-/mermaid-{latest}.tgz",
                                               "integrity": "sha512-NUEVA"}}}}
    return get_json


def test_up_to_date(vendor):
    current = vendor.PACKAGES["mermaid"]["version"]
    assert vendor.outdated(_registry(vendor, current, "2026-01-01T00:00:00.000Z"), NOW) == []
    assert "al día" in vendor.report([])


def test_new_version_only_after_two_weeks(vendor):
    assert vendor.outdated(_registry(vendor, "99.0.0", "2026-11-15T00:00:00.000Z"), NOW) == []   # 5 días: espera
    [item] = vendor.outdated(_registry(vendor, "99.0.0", "2026-11-01T00:00:00.000Z"), NOW)
    assert item["latest"] == "99.0.0" and item["integrity"] == "sha512-NUEVA"
    text = vendor.report([item])
    assert '"version": "99.0.0",' in text and '"integrity": "sha512-NUEVA",' in text


def test_advisories_even_without_a_new_version(vendor):
    current = vendor.PACKAGES["mermaid"]["version"]
    adv = {"title": "XSS en etiquetas", "severity": "high", "url": "https://github.com/advisories/GHSA-x",
           "vulnerable_versions": f"<={current}"}
    [item] = vendor.outdated(_registry(vendor, current, "2026-01-01T00:00:00.000Z", [adv]), NOW)
    assert item["latest"] == "" and item["advisories"][0]["severity"] == "high"
    assert "Aviso de seguridad (high)" in vendor.report([item])

"""Versiones nuevas y vulnerabilidades conocidas (core/advisories.py) con la red simulada: la aritmética de CVSS, que
OSV contesta en el orden preguntado, una vulnerabilidad con varios nombres cuenta una vez, y nada lanza."""
from __future__ import annotations

import json

import pytest

from storageweb.core import advisories as adv


@pytest.mark.parametrize("vector, score", [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:R/S:U/C:H/I:H/A:H", 8.0),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N", 5.5),
    ("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", 1.6),
    ("CVSS:3.1/AV:N/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N", 0.0),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N", 8.6),
    ("CVSS:3.1/AV:L/AC:L/PR:N/UI:N/S:C/C:L/I:L/A:L", 6.8),
    ("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H", 7.5),
])
def test_cvss_scores_as_the_specification_says(vector, score):
    assert adv.cvss_score(vector) == score


@pytest.mark.parametrize("vector", ["CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P", "CVSS:3.1/AV:N/AC:L",
                                    "CVSS:3.1/AV:Z/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "nada", "", None])
def test_what_is_not_a_vector_scores_nothing(vector):
    assert adv.cvss_score(vector) is None


@pytest.mark.parametrize("score, band", [(0.0, "none"), (3.9, "low"), (4.0, "moderate"), (7.0, "high"),
                                         (9.0, "critical"), (None, "")])
def test_bands(score, band):
    assert adv.rating_of(score) == band


def test_versions_compare_and_unknown_is_not_a_verdict():
    assert adv.compare("3.1.0", "3.2.0") == "behind" and adv.compare("3.2.0", "3.2.0") == "current"
    assert adv.compare("1.0", "") == "unknown" and adv.compare("x", "y") == "unknown"


def test_links_are_built_here():
    assert adv.advisory_url("GHSA-abcd-1234") == "https://osv.dev/vulnerability/GHSA-abcd-1234"
    assert adv.advisory_url("javascript:alert(1)") == "" and adv.advisory_url("../x") == ""
    assert adv.project_url("npm", "mermaid", "12.3.0") == "https://www.npmjs.com/package/mermaid/v/12.3.0"
    assert adv.latest_version(("PyPI", "../../etc"))["error"] == "bad_name"


def test_aliases_count_once():
    details = {"GHSA-1": {"ok": True, "published": True, "aliases": ["PYSEC-9", "CVE-2026-1"]},
               "PYSEC-9": {"ok": True, "published": False, "aliases": ["GHSA-1"]}}
    under = adv.collapse_aliases(["PYSEC-9", "GHSA-1"], details)
    assert under == {"GHSA-1": "GHSA-1", "PYSEC-9": "GHSA-1"}


@pytest.fixture
def network(monkeypatch):
    """Respuestas por URL; lo que no está, inalcanzable."""
    answers: dict = {}
    asked: list = []

    def fake(url, timeout, data=None):
        asked.append((url, json.loads(data) if data else None))
        got = answers.get(url)
        if got is None:
            return {"ok": False, "error": "unreachable"}
        return got(data) if callable(got) else {"ok": True, "data": got}

    monkeypatch.setattr(adv, "_get_json", fake)
    return answers, asked


def test_full_check(network):
    answers, asked = network
    answers[adv.PYPI_URL.format(name="flask")] = {"info": {"version": "3.2.0"}}
    answers[adv.PYPI_URL.format(name="waitress")] = {"info": {"version": "3.0.2"}}
    answers[adv.NPM_URL.format(name="mermaid")] = {"version": "12.3.0"}
    answers[adv.OSV_BATCH_URL] = {"results": [{"vulns": [{"id": "GHSA-aaaa-1111"}, {"id": "PYSEC-2026-1"}]},
                                              {}, {"vulns": [{"id": "<script>"}]}]}
    answers[adv.OSV_VULN_API.format(vid="GHSA-aaaa-1111")] = {
        "aliases": ["PYSEC-2026-1"], "summary": "Algo grave", "database_specific": {"severity": "HIGH"},
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]}
    answers[adv.OSV_VULN_API.format(vid="PYSEC-2026-1")] = {"aliases": ["GHSA-aaaa-1111"]}
    rows = [{"name": "flask", "installed": "3.1.0", "ecosystem": "PyPI", "group": "required"},
            {"name": "waitress", "installed": "3.0.2", "ecosystem": "PyPI", "group": "required"},
            {"name": "mermaid", "installed": "12.3.0", "ecosystem": "npm", "group": "javascript"},
            {"name": "raro", "installed": "1", "ecosystem": "Maven", "group": "other"}]        # otro ecosistema: fuera
    result = adv.check(rows)
    assert result["vulns_ok"] and result["vuln_asked"] == 3 and result["checked"] == 3
    flask = result["rows"][0]                                    # el vulnerable, primero
    assert flask["name"] == "flask" and flask["state"] == "behind" and flask["latest"] == "3.2.0"
    assert [v["id"] for v in flask["vulns"]] == ["GHSA-aaaa-1111"]          # un fallo, dos nombres: una vez
    assert flask["vulns"][0]["aliases"] == ["PYSEC-2026-1"] and flask["vulns"][0]["severity"] == "high"
    assert flask["vulns"][0]["score"] == 9.8 and flask["url"] == "https://pypi.org/project/flask/3.2.0/"
    mermaid = next(r for r in result["rows"] if r["name"] == "mermaid")
    assert mermaid["vulns"] == [] and mermaid["state"] == "current"         # «<script>» no es un identificador
    assert (flask["kind"], mermaid["kind"]) == ("Python", "JavaScript")     # la columna Tipo
    assert result["vuln_total"] == 1 and result["vuln_packages"] == 1 and result["worst"] == "high"
    batch = next(body for url, body in asked if url == adv.OSV_BATCH_URL)
    assert {"package": {"name": "mermaid", "ecosystem": "npm"}, "version": "12.3.0"} in batch["queries"]


def test_osv_down_or_answering_the_wrong_length(network):
    answers, _asked = network
    rows = [{"name": "flask", "installed": "3.1.0", "ecosystem": "PyPI"}]
    result = adv.check(rows)                                     # nada contesta: valores, no excepciones
    assert not result["vulns_ok"] and result["vulns_error"] == "unreachable" and result["vuln_total"] == 0
    assert result["rows"][0]["state"] == "unknown" and result["rows"][0]["error"] == "unreachable"
    answers[adv.OSV_BATCH_URL] = {"results": []}
    assert adv.check(rows)["vulns_error"] == "length_mismatch"


def test_the_overview_alert():
    from types import SimpleNamespace
    assert adv._vulnerable_packages(SimpleNamespace(maint_state={})) == []
    found = adv._vulnerable_packages(SimpleNamespace(maint_state={"advisories": {
        "vuln_total": 2, "worst": "critical", "at": "2026-11-21T10:00:00+00:00"}}))
    assert found[0]["level"] == "danger" and found[0]["page"] == "vulnerabilities" and "2026-11-21" in found[0]["detail"]
    moderate = adv._vulnerable_packages(SimpleNamespace(maint_state={"advisories": {"vuln_total": 1,
                                                                                     "worst": "moderate"}}))
    assert moderate[0]["level"] == "warn"

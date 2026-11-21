"""Sistema → Información: versión, proceso, máquina, base de datos, carpetas y componentes (core/diagnostics.py), y el
informe para una incidencia. Nada lanza, nada escribe y nada lleva secretos."""
from __future__ import annotations

import json
import sqlite3

from storageweb import __version__
from storageweb.core import diagnostics
from storageweb.db.connection import available_migrations
from tests.integration.test_mfa import last_audit


def test_the_page_shows_each_block(app, admin):
    client, _token = admin
    page = client.get("/admin/settings/system").get_data(as_text=True)
    for text in ("Esta instalación", f"StorageWeb <strong>{__version__}</strong>", "Se ejecuta como", "Hora del servidor",
                 "Sistema operativo", "Esquema", "al día", "Carpetas", "Datos", "Componentes",
                 "Cómo ha llegado esta página", "/admin/settings/system/report?format=txt",
                 "mermaid", "highlight.js", "Dibujar los diagramas Mermaid"):
        assert text in page, text
    assert "Arranque (solo config.json" in page                     # lo de antes sigue


def test_report_in_text_and_json_without_secrets(app, admin, make_app):
    client, _token = admin
    text = client.get("/admin/settings/system/report")
    assert text.status_code == 200 and text.mimetype == "text/plain"
    assert "attachment;" in text.headers["Content-Disposition"] and ".txt" in text.headers["Content-Disposition"]
    body = text.get_data(as_text=True)
    assert body.startswith(f"StorageWeb {__version__}") and "[database]" in body and "[folders]" in body
    data = client.get("/admin/settings/system/report?format=json").get_json(force=True)
    assert set(data) == {"generated", "system", "database", "folders", "components", "javascript", "network"}
    assert {lib["name"] for lib in data["javascript"]} == {"mermaid", "highlight.js"}
    assert all(lib["status"] == "ok" and lib["version"] for lib in data["javascript"])
    assert data["database"]["schema"] == available_migrations()[-1][0]
    assert last_audit(app, "system_report")["detail"] == "json"
    secret = app.secret_key if isinstance(app.secret_key, str) else app.secret_key.decode("latin-1")
    assert secret
    assert secret not in body and secret not in json.dumps(data)
    # Solo administradores
    assert app.test_client().get("/admin/settings/system/report").status_code in (302, 403)


def test_folders_states(tmp_path):
    (tmp_path / "datos").mkdir()
    rows = diagnostics.folders([{"key": "data", "path": str(tmp_path / "datos")},
                                {"key": "same", "path": str(tmp_path)},
                                {"key": "later", "path": str(tmp_path / "aun-no"), "on_demand": True},
                                {"key": "gone", "path": str(tmp_path / "no-esta")}])
    data, same, later, gone = rows
    assert data["exists"] and data["writable"] and data["total"] > 0
    assert same["exists"] and same["total"] == 0              # el mismo disco: el espacio sale una vez
    assert not later["exists"] and later["on_demand"]
    assert not gone["exists"] and not gone["on_demand"]
    assert not (tmp_path / "aun-no").exists()                # nada se crea


def test_components_and_stale_metadata(monkeypatch):
    requires = ['Flask<4,>=3.0', 'python-pam<3,>=2.0; sys_platform != "win32"', 'nada-instalado>=1',
                'boto3>=1.28; extra == "s3"', 'pytest<10,>=8; extra == "dev"', 'cosa-windows; sys_platform == "win32"']
    versions = {"Flask": "3.1.0", "python-pam": "2.0.2", "boto3": "", "storageweb": "0.0.1", "cosa-windows": "1"}
    monkeypatch.setattr(diagnostics.metadata, "requires", lambda name: requires)
    monkeypatch.setattr(diagnostics, "_installed", lambda name: versions.get(name, ""))
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    comp = diagnostics.components()
    names = [r["name"] for r in comp["required"]]
    assert names == ["nada-instalado", "Flask", "python-pam"]          # lo que falta, primero; Windows no aplica
    assert comp["missing"] == 1 and comp["required"][0]["status"] == "missing"
    assert [r["name"] for r in comp["optional"]] == ["boto3"]          # dev no es del servidor
    assert comp["optional"][0]["feature"] != "s3"                      # el nombre del tipo de ubicación, de su esquema
    assert comp["stale"] and comp["dist_version"] == "0.0.1"


def test_database_and_system_never_fail(tmp_path):
    path = tmp_path / "x.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 3")
    info = diagnostics.database(conn, str(path))
    assert info["schema"] == 3 and info["engine"].startswith("SQLite ") and info["size"] > 0
    sy = diagnostics.system()
    assert sy["version"] == __version__ and sy["pid"] > 0 and sy["cpus"] >= 1 and sy["run_mode"]
    assert diagnostics.home_base("/srv/homes/{username}") == "/srv/homes"
    assert diagnostics.as_text({"generated": "x", "system": sy}).startswith("StorageWeb ")


def test_vendored_javascript_is_checked_file_by_file(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "a.js").write_text("uno", encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(b"uno").hexdigest()
    (tmp_path / "vendor.json").write_text(json.dumps({
        "a": {"package": "a", "version": "1.0.0", "setting": "", "files": {"lib/a.js": digest}},
        "b": {"package": "b", "version": "2.0.0", "setting": "", "files": {"lib/b.js": digest}}}), encoding="utf-8")
    rows = {r["name"]: r for r in diagnostics.vendored(tmp_path)}
    assert rows["a"]["status"] == "ok" and rows["b"]["status"] == "missing"
    (lib / "a.js").write_text("tocado", encoding="utf-8")
    assert diagnostics.vendored(tmp_path)[0]["status"] == "modified"
    assert diagnostics.vendored(tmp_path / "no-esta") == []


def test_vulnerability_check_from_the_page(app, admin, monkeypatch):
    from storageweb.core import advisories
    client, token = admin
    page = client.get("/admin/settings/vulnerabilities").get_data(as_text=True)
    assert 'id="advisories"' in page and "Nunca se ha comprobado" in page          # nada sale solo
    asked = {}

    def fake_check(rows, timeout=advisories.TIMEOUT, progress=None):
        asked["rows"] = rows
        return {"at": "2026-11-21T10:00:00+00:00", "checked": 2, "behind": 1, "vulns_ok": True, "vulns_error": "",
                "vuln_asked": 2, "vuln_total": 1, "vuln_packages": 1, "worst": "critical",
                "rows": [{"name": "flask", "ecosystem": "PyPI", "kind": "Python", "group": "required", "installed": "3.1.0",
                          "latest": "3.2.0", "state": "behind", "url": "https://pypi.org/project/flask/3.2.0/",
                          "error": "", "vulns": [{"id": "GHSA-aaaa-1111", "url": "https://osv.dev/vulnerability/GHSA-aaaa-1111",
                                                  "aliases": [], "severity": "critical", "score": 9.8,
                                                  "published": False, "summary": "Algo grave"}]},
                         {"name": "mermaid", "ecosystem": "npm", "kind": "JavaScript", "group": "javascript", "installed": "12.3.0",
                          "latest": "12.3.0", "state": "current", "url": "", "error": "", "vulns": []}]}

    monkeypatch.setattr(advisories, "check", fake_check)
    assert client.get("/admin/settings/system/advisories").status_code == 405        # solo POST (sale a internet)
    resp = client.post("/admin/settings/system/advisories", data={"_csrf": token})
    assert resp.status_code == 302 and resp.location.endswith("/admin/settings/vulnerabilities#advisories")
    # La lista la hace el servidor: lo instalado (sin StorageWeb) y el JavaScript copiado, con su nombre en OSV
    names = {(r["ecosystem"], r["name"]) for r in asked["rows"]}
    assert ("npm", "mermaid") in names and ("npm", "highlight.js") in names
    assert any(e == "PyPI" and n.lower() == "flask" for e, n in names)
    assert not any(n.lower() == "storageweb" for _e, n in names)
    page = client.get("/admin/settings/vulnerabilities").get_data(as_text=True)
    assert "GHSA-aaaa-1111" in page and "crítica 9.8" in page and "Algo grave" in page and "1 vulnerabilidad" in page
    assert "https://osv.dev/vulnerability/GHSA-aaaa-1111" in page
    assert ">Tipo</th>" in page and "<td>JavaScript</td>" in page and "<td>Python</td>" in page
    assert last_audit(app, "dependencies_checked")["detail"].startswith("packages=2 vulnerable=1 advisories=1")
    overview = client.get("/admin/").get_data(as_text=True)
    assert "vulnerabilidad conocida en las bibliotecas instaladas" in overview
    # Solo administradores
    assert app.test_client().post("/admin/settings/system/advisories").status_code in (302, 400, 403)

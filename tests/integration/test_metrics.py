"""/metrics: acceso (token, redes, solo el servidor), formato de Prometheus y contenido."""
import io
import re

import pytest

from storageweb import metrics
from storageweb.core import monitoring, quota
from storageweb.web.context import get_db, settings
from tests.helpers import get_csrf, login, update_settings, signed_in

TOKEN = "prometheus-token-1234567890"
OTHER = {"REMOTE_ADDR": "203.0.113.9"}
LINE = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{([a-zA-Z_][a-zA-Z0-9_]*="([^"\\]|\\.)*",?)*\})? '
                  r'(-?[0-9.e+-]+|NaN|[+-]Inf)$')


@pytest.fixture
def app(make_app, tmp_path):
    metrics.clear()
    monitoring.reset()
    quota.clear()
    shared = tmp_path / "equipo"
    shared.mkdir()
    (shared / "a.bin").write_bytes(b"x" * 1000)
    yield make_app({"metrics": {"enabled": True},
                    "storage": {"shares": [{"name": "equipo", "label": "Equipo", "path": str(shared), "users": ["*"],
                                            "quota_mb": 5}]}})
    metrics.clear()
    monitoring.reset()


def _set_metrics(app, **values):
    update_settings(app, metrics=values)


def test_disabled_metrics_do_not_exist(make_app):
    assert make_app().test_client().get("/metrics").status_code == 404


def test_access_by_server_networks_and_token(app):
    client = app.test_client()
    assert client.get("/metrics").status_code == 200                                 # desde el propio servidor
    assert client.get("/metrics", environ_base=OTHER).status_code == 403             # desde fuera, no
    _set_metrics(app, allowed_networks=["203.0.113.0/24"])
    assert client.get("/metrics", environ_base=OTHER).status_code == 200
    assert client.get("/metrics", environ_base={"REMOTE_ADDR": "198.51.100.1"}).status_code == 403
    _set_metrics(app, allowed_networks=[], token=TOKEN)
    assert client.get("/metrics").status_code == 403                                 # con token, también el servidor
    ok = client.get("/metrics", environ_base=OTHER, headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200 and ok.headers["Content-Type"].startswith("text/plain; version=0.0.4")
    bad = client.get("/metrics", environ_base=OTHER, headers={"Authorization": "Bearer otro-token-que-no-vale"})
    assert bad.status_code == 403                                                    # ni un 401 de token de API
    with app.app_context():
        offenses = get_db().execute("SELECT COUNT(*) FROM ip_offenses WHERE ip = ?", ("203.0.113.9",)).fetchone()[0]
    assert offenses == 1


def test_content_and_format(app, tmp_path):
    client, _ = signed_in(app, "ana", csrf_url=None)
    login(app.test_client(), "ana", password="mala")
    token = get_csrf(client, "/f/home/")
    client.post("/upload/home/", data={"files": [(io.BytesIO(b"y" * 2048), "a.txt")]},
                headers={"X-CSRF-Token": token, "Accept": "application/json"}, content_type="multipart/form-data")
    assert client.get("/download/home/a.txt").status_code == 200
    with app.app_context():
        monitoring.refresh(settings())                                             # lo que hace la tarea periódica
    body = client.get("/metrics").get_data(as_text=True)
    for line in body.splitlines():
        assert line.startswith("# ") or LINE.match(line), line                     # formato de Prometheus
    assert re.search(r'^storageweb_info\{version="[^"]+"\} 1$', body, re.M)
    assert 'storageweb_users{source="local",state="enabled"} 1' in body
    assert 'storageweb_events_total{action="login"} 1' in body
    assert 'storageweb_events_total{action="login_failed"} 1' in body
    assert 'storageweb_upload_bytes_total{via="web"} 2048' in body
    assert 'storageweb_download_bytes_total{via="web"} 2048' in body
    assert 'storageweb_folder_used_bytes{folder="equipo"} 1000' in body
    assert f'storageweb_folder_quota_bytes{{folder="equipo"}} {5 * 1024 * 1024}' in body
    assert re.search(r'^storageweb_http_requests_total\{code="200",endpoint="files.browse",method="GET"\} \d+$',
                     body, re.M)
    assert "# TYPE storageweb_http_request_duration_seconds summary" in body
    assert 'storageweb_alerts{level="danger"}' in body and "storageweb_database_size_bytes" in body


def test_settings_in_the_monitoring_page(app):
    admin, _ = signed_in(app, "root", role="admin", csrf_url=None)
    page = admin.get("/admin/settings/monitoring").get_data(as_text=True)
    assert 'name="metrics_enabled"' in page and "/metrics" in page
    form = {"_csrf": get_csrf(admin, "/admin/settings/monitoring"), "audit_retention_days": "0",
            "backup_interval_hours": "0", "backup_keep": "7", "offsite_keep": "14", "metrics_enabled": "on", "metrics_token": TOKEN,
            "metrics_allowed_networks": "10.0.0.5, 192.168.10.0/24"}
    admin.post("/admin/settings/monitoring", data=form)
    with app.app_context():
        cfg = settings()["metrics"]
    assert cfg == {"enabled": True, "token": TOKEN, "allowed_networks": ["10.0.0.5/32", "192.168.10.0/24"]}
    admin.post("/admin/settings/monitoring", data={**form, "metrics_token": ""})    # vacío = se conserva
    with app.app_context():
        assert settings()["metrics"]["token"] == TOKEN
    html = admin.post("/admin/settings/monitoring", data={**form, "metrics_allowed_networks": "no-es-una-red"})
    assert "no es una dirección IP ni una red" in html.get_data(as_text=True)

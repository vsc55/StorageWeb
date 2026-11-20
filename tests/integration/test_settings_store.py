"""Ajustes web por campo (``settings.store``): una fila por perfil y campo, quién y cuándo, y guardados que no se
pisan."""
import json

from storageweb.settings import runtime_view, store
from storageweb.web.context import get_db, runtime, settings
from tests.helpers import add_user, get_csrf, login


def test_flatten_keeps_lists_and_leaf_dicts_whole():
    doc = {"app_name": "X", "auth": {"entra": {"tenant_id": "t", "role_mappings": {"g1": "admin"}}},
           "storage": {"shares": [{"name": "a"}], "group_quotas": {}}, "network": {}}
    flat = store.flatten(doc)
    assert flat == {"app_name": "X", "auth.entra.tenant_id": "t", "auth.entra.role_mappings": {"g1": "admin"},
                    "storage.shares": [{"name": "a"}], "storage.group_quotas": {}}
    assert store.unflatten(flat) == {k: v for k, v in doc.items() if k != "network"}


def _rows(app):
    with app.app_context():
        return {r["path"]: dict(r) for r in get_db().execute("SELECT * FROM settings_values WHERE profile = 'default'")}


def _save_general(client, name):
    form = {"_csrf": get_csrf(client, "/admin/settings/general"), "app_name": name, "default_locale": "es",
            "primary_color": ""}
    return client.post("/admin/settings/general", data=form)


def test_one_row_per_field_with_who_and_when(make_app):
    app = make_app()
    add_user(app, "ana", role="admin")
    add_user(app, "eva", role="admin")
    ana, eva = app.test_client(), app.test_client()
    login(ana, "ana")
    login(eva, "eva")
    _save_general(ana, "Archivos")
    rows = _rows(app)
    assert json.loads(rows["app_name"]["value"]) == "Archivos" and rows["app_name"]["updated_by"] == "ana"
    form = {"_csrf": get_csrf(eva, "/admin/settings/audit_settings"), "audit_retention_days": "30",
            "backup_interval_hours": "0", "backup_keep": "7", "offsite_keep": "14", "metrics_allowed_networks": ""}
    eva.post("/admin/settings/audit_settings", data=form)
    rows = _rows(app)
    assert rows["app_name"]["updated_by"] == "ana"                            # no lo tocó quien guardó otra cosa
    assert rows["maintenance.audit_retention_days"]["updated_by"] == "eva"
    page = ana.get("/admin/settings/system").get_data(as_text=True)
    assert "Perfil de ajustes" in page and "<code>default</code>" in page and "· ana" in page and "· eva" in page

    with app.app_context():                                                  # restablecer: se va solo esa fila
        runtime().reset_path(get_db(), "app_name", "ana")
    assert "app_name" not in _rows(app) and "maintenance.audit_retention_days" in _rows(app)


def test_concurrent_saves_of_different_things_do_not_overwrite_each_other(make_app):
    app = make_app()
    with app.test_request_context():
        stale = runtime_view(settings())                                     # lo que tenía en pantalla el admin A
    with app.test_request_context():
        base = runtime_view(settings())
        runtime().save(get_db(), {**base, "app_name": "De B"}, "b", base=base)       # B guarda antes
    with app.test_request_context():
        mine = json.loads(json.dumps(stale))
        mine["maintenance"]["audit_retention_days"] = 90
        runtime().save(get_db(), mine, "a", base=stale)                     # A, con su vista vieja
    with app.test_request_context():
        assert settings()["app_name"] == "De B"                             # no se pierde lo de B
        assert settings()["maintenance"]["audit_retention_days"] == 90

"""Carpetas compartidas, ubicaciones y cuotas de grupo en sus propias tablas: las de config.json de solo lectura
junto a las de la web, secretos cifrados y guardados que no se pisan."""
import json

from storageweb import create_app
from storageweb.core import groups as gc
from storageweb.settings import runtime_view
from storageweb.web.context import get_db, runtime, settings
from tests.helpers import add_user, get_csrf, login, update_settings, G

SMB = {"name": "nas", "label": "NAS", "type": "smb", "server": "nas.local", "share": "datos", "username": "u",
       "password": "clave-smb"}


def _db(app, sql, *args):
    with app.app_context():
        return [dict(r) for r in get_db().execute(sql, args)]


def test_shares_and_locations_live_in_their_tables(make_app, tmp_path):
    app = make_app({"storage": {"locations": [SMB], "shares": [
        {"name": "obra", "label": "Obra", "path": str(tmp_path / "obra"), "users": ["ana"], "read_only_users": ["ana"],
         "groups": ["rrhh"]},
        {"name": "nas-docs", "label": "Docs", "location": "nas", "path": "docs"}]}})
    assert [r["name"] for r in _db(app, "SELECT name FROM shares ORDER BY position")] == ["obra", "nas-docs"]
    assert {(r["kind"], r["ref"], r["level"]) for r in _db(app, "SELECT * FROM share_access WHERE share = 'obra'")} == \
        {("user", "ana", "read"), ("group", "rrhh", "write")}
    assert _db(app, "SELECT ref FROM share_access WHERE share = 'nas-docs'") == [{"ref": "*"}]   # sin users: todos
    options = {r["name"]: r for r in _db(app, "SELECT * FROM location_options WHERE location = 'nas'")}
    assert options["server"]["value"] == '"nas.local"'
    assert _db(app, "SELECT COUNT(*) AS n FROM settings_values WHERE path IN "
                    "('storage.shares', 'storage.locations', 'storage.group_quotas')")[0]["n"] == 0
    with app.test_request_context():
        shares = settings()["storage"]["shares"]
        assert [(s["name"], s["origin"]) for s in shares] == [("obra", "web"), ("nas-docs", "web")]
        assert shares[0]["read_only_users"] == ["ana"] and shares[0]["groups"] == ["rrhh"]


def test_web_share_can_use_a_location_from_config_json(write_config, tmp_path):
    path = write_config({"storage": {"locations": [SMB], "group_quotas": {"admins": 10}}})
    app = create_app(str(path))
    app.testing = True
    with app.test_request_context():
        base = runtime_view(settings())
        new = json.loads(json.dumps(base))
        new["storage"]["shares"].append({"name": "docs", "label": "Docs", "location": "nas", "path": "docs",
                                         "users": ["*"]})
        runtime().save(get_db(), new, "root", strict=True, base=base)
    with app.test_request_context():
        cfg = settings()["storage"]
        assert [(s["name"], s["location"], s["origin"]) for s in cfg["shares"]] == [("docs", "nas", "web")]
        assert [(loc["name"], loc["origin"]) for loc in cfg["locations"]] == [("nas", "file")]
        assert runtime().config_entities()["group_quotas"] == {"admins"}
        base = runtime_view(settings())
        changed = json.loads(json.dumps(base))
        changed["storage"]["group_quotas"]["admins"] = 99                    # la de config.json no se cambia
        try:
            runtime().save(get_db(), changed, "root", strict=True, base=base)
            raise AssertionError("debía rechazarse")
        except Exception as exc:  # noqa: BLE001
            assert "config.json" in str(exc)


def test_two_admins_editing_different_shares_do_not_overwrite_each_other(make_app, tmp_path):
    app = make_app({"storage": {"shares": [
        {"name": "a", "label": "A", "path": str(tmp_path / "a")}, {"name": "b", "label": "B", "path": str(tmp_path / "b")}]}})
    with app.test_request_context():
        stale = runtime_view(settings())                     # lo que tenía en pantalla el admin 1
    with app.test_request_context():
        base = runtime_view(settings())
        mine = json.loads(json.dumps(base))
        mine["storage"]["shares"][1]["label"] = "B de Eva"
        runtime().save(get_db(), mine, "eva", strict=True, base=base)
    with app.test_request_context():
        mine = json.loads(json.dumps(stale))
        mine["storage"]["shares"][0]["label"] = "A de Ana"
        runtime().save(get_db(), mine, "ana", strict=True, base=stale)
    rows = {r["name"]: r for r in _db(app, "SELECT * FROM shares")}
    assert (rows["a"]["label"], rows["a"]["updated_by"]) == ("A de Ana", "ana")
    assert (rows["b"]["label"], rows["b"]["updated_by"]) == ("B de Eva", "eva")


def test_group_quota_is_a_column_of_the_group(make_app):
    app = make_app()
    add_user(app, "root", role="admin")
    with app.app_context():
        gid = gc.create_group(get_db(), name="rrhh", label="RRHH")
    admin = app.test_client()
    login(admin, "root")
    form = {"_csrf": get_csrf(admin, f"/admin/groups/{G(gid)}"), "label": "RRHH", "description": "", "source": "local",
            "external_id": "", "home_quota_mb": "30"}
    admin.post(f"/admin/groups/{G(gid)}", data=form)
    assert _db(app, "SELECT home_quota_mb FROM groups WHERE name = 'rrhh'") == [{"home_quota_mb": 30}]
    with app.test_request_context():
        assert settings()["storage"]["group_quotas"] == {"rrhh": 30}
    update_settings(app, storage={"group_quotas": {}})       # como si se quitaran todas
    assert _db(app, "SELECT home_quota_mb FROM groups WHERE name = 'rrhh'") == [{"home_quota_mb": None}]

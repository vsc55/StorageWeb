"""Integración con el directorio de Entra ID: revisión periódica de las cuentas, usuarios con más de 200 grupos,
cierre de sesión de canal frontal, cambio de UPN y datos de los grupos dados de alta (Microsoft simulado)."""
from __future__ import annotations

from pathlib import Path

import pytest

from storageweb.core import accounts, tokens
from storageweb.core import groups as gc
from storageweb.db.repositories import audit, sessions, users
from storageweb.db.repositories import groups as group_repo
from storageweb.providers.entra import directory as entra_directory
from storageweb.web.context import get_db, settings
from tests.helpers import add_user, U, G
from tests.sso_helpers import entra_cfg, sso_login

G_SALES, G_IT = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def directory(monkeypatch):
    """Directorio simulado: ``states[oid]`` = lo que devuelve ``user_state``; ``groups`` = getMemberGroups."""
    class Directory:
        states: dict = {}
        groups: list | None = None
        details: dict = {}
        asked: list = []

    d = Directory()
    d.states, d.details, d.asked = {}, {}, []
    monkeypatch.setattr(entra_directory, "user_state", lambda ecfg, oid: (d.asked.append(oid), d.states.get(oid))[1])
    monkeypatch.setattr(entra_directory, "member_groups", lambda ecfg, oid: d.groups)
    monkeypatch.setattr(entra_directory, "info_for", lambda ecfg, ids: {i: d.details[i] for i in ids if i in d.details})
    return d


def _actions(app, n=20):
    with app.app_context():
        return [(r["action"], r["detail"]) for r in audit.recent(get_db(), n)]


def _user(app, oid="oid-juan"):
    with app.app_context():
        return users.get_by_external(get_db(), "entra", oid)


def _sync(app):
    with app.app_context():
        return accounts.sync_directory(get_db(), settings())


# --------------------------------------------------------------------------- revisión periódica (1)

def test_accounts_with_access_are_checked_and_disabled(entra_app, token_endpoint, directory):
    app = entra_app(role_mappings={G_IT: "admin"})
    browser = app.test_client()
    sso_login(browser, token_endpoint, groups=[G_SALES])
    juan = _user(app)
    with app.app_context():
        plain, _id = tokens.create(get_db(), juan, name="vscode", scope="write", days=0)
    idle = add_user(app, "ana@contoso.com", password=None, source="entra", external_id="oid-ana")  # sin acceso

    # Sigue en Entra ID: cambian sus grupos (y con ellos el rol)
    directory.states["oid-juan"] = {"exists": True, "enabled": True, "groups": [G_IT]}
    summary = _sync(app)["entra"]
    assert directory.asked == ["oid-juan"]                      # la cuenta sin sesión ni token no se consulta
    assert summary["checked"] == 1 and summary["updated"] == 1
    juan = _user(app)
    assert gc.split(juan["external_groups"]) == {G_IT} and juan["role"] == "admin"
    assert ("role_changed", "none->admin (entra:directory)") in _actions(app)

    # La desactivan en Entra ID: fuera sesiones y tokens
    directory.states["oid-juan"] = {"exists": True, "enabled": False}
    assert _sync(app)["entra"]["disabled"] == 1
    juan = _user(app)
    assert not juan["enabled"] and juan["disabled_reason"] == "directory"
    with app.app_context():
        assert sessions.count_for_user(get_db(), juan["id"]) == 0
        assert tokens.authenticate(get_db(), plain) is None
    assert browser.get("/f/home/").status_code == 302
    assert any(a == "user_disabled" and d.startswith("entra:disabled") for a, d in _actions(app))
    html = _admin_page(app, f"/admin/users/{U(juan['id'])}")
    assert "Desactivada automáticamente" in html

    # La vuelven a activar: se reactiva sola y el token vuelve a valer
    directory.states["oid-juan"] = {"exists": True, "enabled": True, "groups": [G_IT]}
    assert _sync(app)["entra"]["enabled"] == 1
    with app.app_context():
        assert tokens.authenticate(get_db(), plain) is not None
    assert idle and _user(app, "oid-ana")["enabled"]


def _admin_page(app, url):
    if not users_exists(app, "root"):
        add_user(app, "root", role="admin")
    admin = app.test_client()
    from tests.helpers import login
    login(admin, "root")
    return admin.get(url).get_data(as_text=True)


def users_exists(app, name):
    with app.app_context():
        return users.get_by_username(get_db(), name) is not None


def test_deleted_or_not_allowed_accounts_and_unknown_state(entra_app, token_endpoint, directory):
    app = entra_app(allowed_groups=[G_SALES])
    sso_login(app.test_client(), token_endpoint, groups=[G_SALES])
    directory.states["oid-juan"] = None                          # Graph no responde: no se toca nada
    assert _sync(app)["entra"]["unknown"] == 1 and _user(app)["enabled"]
    directory.states["oid-juan"] = {"exists": True, "enabled": True, "groups": [G_IT]}   # fuera del grupo permitido
    _sync(app)
    assert not _user(app)["enabled"]
    assert any(a == "user_disabled" and d.startswith("entra:not_allowed") for a, d in _actions(app))
    directory.states["oid-juan"] = {"exists": False}             # borrada en Entra ID
    _sync(app)
    assert not _user(app)["enabled"] and _user(app)["disabled_reason"] == "directory"


def test_directory_disabled_account_comes_back_on_sign_in_but_not_a_manual_one(entra_app, token_endpoint, directory):
    app = entra_app()
    client = app.test_client()
    sso_login(client, token_endpoint)
    with app.app_context():
        users.update(get_db(), _user(app)["id"], enabled=False, disabled_reason="directory")
    client = app.test_client()
    assert sso_login(client, token_endpoint).status_code == 302 and client.get("/f/home/").status_code == 200
    assert _user(app)["enabled"] and _user(app)["disabled_reason"] is None
    with app.app_context():                                     # desactivada por un admin: no entra
        accounts.set_enabled(get_db(), _user(app), {"id": -1}, False)
    client = app.test_client()
    sso_login(client, token_endpoint)
    assert client.get("/f/home/").status_code == 302 and not _user(app)["enabled"]


def test_sync_is_a_maintenance_task_that_follows_the_setting(entra_app, make_app):
    from storageweb.core import maintenance
    app = entra_app(directory_sync_minutes=30)
    with app.app_context():
        task = next(t for t in maintenance.tasks() if t.name == "directory_sync")
        assert task.every(settings()) == 0.5
    app = entra_app(directory_sync_minutes=0)
    with app.app_context():
        assert task.every(settings()) == 0
    app = make_app()                                            # sin Entra ID
    with app.app_context():
        assert task.every(settings()) == 0


# --------------------------------------------------------------------------- más de 200 grupos (2)

def test_groups_overage_reads_them_from_graph(entra_app, token_endpoint, directory):
    app = entra_app()
    overage = {"_claim_names": {"groups": "src1"}, "_claim_sources": {"src1": {"endpoint": "https://graph"}}}
    directory.groups = [G_SALES, G_IT]
    sso_login(app.test_client(), token_endpoint, roles=["StorageWeb.User"], **overage)
    assert gc.split(_user(app)["external_groups"]) == {G_SALES, G_IT, "storageweb.user"}
    directory.groups = None                                      # no se pueden leer: se conservan los de antes
    sso_login(app.test_client(), token_endpoint, **overage)
    assert gc.split(_user(app)["external_groups"]) == {G_SALES, G_IT, "storageweb.user"}


def test_groups_overage_with_allowed_groups_and_no_graph_is_denied(entra_app, token_endpoint, directory):
    app = entra_app(allowed_groups=[G_SALES])
    client = app.test_client()
    directory.groups = None
    sso_login(client, token_endpoint, hasgroups=True)
    assert _user(app) is None
    assert ("login_denied", "entra:groups_unknown") in _actions(app)
    assert "No se pudieron leer tus grupos" in client.get("/login?manual=1").get_data(as_text=True)
    directory.groups = [G_SALES]
    sso_login(client, token_endpoint, hasgroups=True)
    assert _user(app) is not None


# --------------------------------------------------------------------------- cierre de sesión de canal frontal (3)

def test_frontchannel_logout_closes_the_sessions_of_that_microsoft_session(entra_app, token_endpoint):
    app = entra_app()
    browser = app.test_client()
    sso_login(browser, token_endpoint, sid="ms-session-1")
    other = app.test_client()
    sso_login(other, token_endpoint, sid="ms-session-2")
    with app.app_context():
        assert {r["provider_sid"] for r in sessions.list_all(get_db())} == {"ms-session-1", "ms-session-2"}
    entra = app.test_client()                                    # el marco de Microsoft: sin la cookie
    resp = entra.get("/auth/entra/frontchannel-logout?sid=ms-session-1&iss=x")
    assert resp.status_code == 200 and "X-Frame-Options" not in resp.headers
    assert "frame-ancestors https://login.microsoftonline.com" in resp.headers["Content-Security-Policy"]
    assert browser.get("/f/home/").status_code == 302           # cerrada
    assert other.get("/f/home/").status_code == 200             # la otra sesión de Microsoft sigue
    assert ("logout", "entra:frontchannel") in _actions(app)
    assert entra.get("/auth/entra/frontchannel-logout").status_code == 200           # sin sid: nada
    assert entra.get("/auth/local/frontchannel-logout?sid=x").status_code == 404     # no es SSO
    assert app.test_client().get("/login").headers["X-Frame-Options"] == "DENY"     # el resto, como siempre


def test_signin_records_whether_the_token_has_sid(entra_app, token_endpoint):
    from storageweb.providers.entra import check
    app = entra_app()
    token_endpoint.response = None
    sso_login(app.test_client(), token_endpoint)
    with app.app_context():
        last = accounts.last_signin_scopes(get_db(), "entra")
    # El token del endpoint simulado no trae «scope»: no se apunta nada; con él, sí
    assert last is None or last.get("claims") == []
    last = {"at": "2026-11-15T10:00:00+00:00", "scopes": ["openid"], "source": "signin", "claims": []}
    result = check._signin_claims(last)
    assert result["ok"] is False and result["fixable"] and "sid" in result["message"]
    assert check._signin_claims({**last, "claims": ["sid"]})["ok"] is True
    assert check._signin_claims({**last, "source": "consent"}) is None


# --------------------------------------------------------------------------- datos de los grupos (5)

def test_registered_groups_follow_the_directory(entra_app, token_endpoint, directory, make_app):
    app = entra_app()
    with app.app_context():
        gid = gc.create_group(get_db(), name="ventas", label="Ventas", description="", source="entra",
                              external_id=G_SALES)
    directory.details[G_SALES] = {"name": "Ventas España", "description": "Equipo comercial"}
    sso_login(app.test_client(), token_endpoint, groups=[G_SALES])         # al entrar
    with app.app_context():
        group = group_repo.get_by_id(get_db(), gid)
    assert (group["label"], group["description"]) == ("Ventas España", "Equipo comercial")
    assert group["name"] == "ventas"                                       # el identificador no cambia

    directory.details[G_SALES] = {"name": "Ventas", "description": "Comercial"}
    directory.states["oid-juan"] = {"exists": True, "enabled": True, "groups": [G_SALES]}
    with app.app_context():
        tokens.create(get_db(), _user(app), name="t", scope="read", days=30)
    assert _sync(app)["entra"]["groups"] == 1                             # en la revisión periódica

    directory.details[G_SALES] = {"name": "Ventas Iberia", "description": "Comercial"}
    html = _admin_page(app, f"/admin/groups/{G(gid)}")                        # y al abrir su ficha, de solo lectura
    assert 'value="Ventas Iberia" maxlength="200" required' in html and "readonly" in html
    assert "se actualizan solos" in html


# --------------------------------------------------------------------------- cambio de UPN (6)

def test_upn_change_renames_the_account_its_home_and_shares(make_app, token_endpoint, tmp_path):
    app = make_app({"auth": {"entra": entra_cfg()},
                    "storage": {"create_shares": True, "shares": [
                        {"name": "obra", "label": "Obra", "path": str(tmp_path / "obra"),
                         "users": ["juan@contoso.com"], "read_only_users": ["juan@contoso.com"], "groups": []}]}})
    client = app.test_client()
    sso_login(client, token_endpoint)
    juan = _user(app)
    with app.app_context():
        from storageweb.core.storage import home_path_for
        old_home = Path(home_path_for(juan, settings()))
    old_home.mkdir(parents=True, exist_ok=True)
    (old_home / "nota.txt").write_text("hola", encoding="utf-8")

    sso_login(app.test_client(), token_endpoint, preferred_username="Juan.Perez@Contoso.com")
    juan = _user(app)
    assert juan["username"] == "juan.perez@contoso.com" and juan["home_path"] is None
    with app.app_context():
        new_home = Path(home_path_for(juan, settings()))
        share = settings()["storage"]["shares"][0]
    assert (new_home / "nota.txt").read_text(encoding="utf-8") == "hola" and not old_home.exists()
    assert share["users"] == ["juan.perez@contoso.com"] and share["read_only_users"] == ["juan.perez@contoso.com"]
    assert ("user_renamed", "juan@contoso.com -> juan.perez@contoso.com; home moved") in _actions(app)
    with app.app_context():
        assert users.count_admins(get_db()) == 0 and len(users.list_all(get_db())) == 1   # la misma cuenta


def test_upn_change_keeps_an_existing_home_and_skips_a_taken_name(entra_app, token_endpoint):
    app = entra_app()
    sso_login(app.test_client(), token_endpoint)
    juan = _user(app)
    with app.app_context():
        from storageweb.core.storage import home_path_for
        old_home = Path(home_path_for(juan, settings()))
        new_home = Path(home_path_for({**dict(juan), "username": "jp@contoso.com"}, settings()))
    old_home.mkdir(parents=True, exist_ok=True)
    new_home.mkdir(parents=True, exist_ok=True)                 # la nueva ya existe: se conserva la antigua
    sso_login(app.test_client(), token_endpoint, preferred_username="jp@contoso.com")
    juan = _user(app)
    assert juan["username"] == "jp@contoso.com" and juan["home_path"] == str(old_home)

    add_user(app, "otro@contoso.com", password=None, source="entra", external_id="oid-otro")
    sso_login(app.test_client(), token_endpoint, preferred_username="otro@contoso.com")
    assert _user(app)["username"] == "jp@contoso.com"           # el nombre ya es de otra cuenta: no se cambia
    assert any(a == "user_rename_failed" for a, _d in _actions(app))

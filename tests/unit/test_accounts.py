"""Lógica de cuentas y roles con una conexión SQLite directa, sin Flask."""
import pytest

from storageweb.core import accounts
from storageweb.core.accounts import AccountError, resolve_role
from storageweb.db.repositories import audit, users
from storageweb.settings import load_config

ECFG = {"role_mappings": {"grp-admins": "admin", "storageweb.user": "user"},
        "default_role": "user", "sync_role_on_login": True}


@pytest.mark.parametrize("groups, current, sync, expected", [
    (["grp-admins"], None, True, "admin"),
    (["storageweb.user", "grp-admins"], None, True, "admin"),   # admin gana
    (["storageweb.user"], None, True, "user"),
    ([], None, True, "user"),                                    # default_role
    ([], "admin", True, "user"),                                 # sync: pierde admin
    ([], "admin", False, "admin"),                               # sin sync: se mantiene
    (["grp-admins"], "user", False, "user"),                     # sin sync: se mantiene
    (["grp-admins"], "user", True, "admin"),
])
def test_resolve_role(groups, current, sync, expected):
    assert resolve_role({**ECFG, "sync_role_on_login": sync}, groups, current) == expected


def test_resolve_role_default_admin():
    cfg = {"role_mappings": {}, "default_role": "admin", "sync_role_on_login": True}
    assert resolve_role(cfg, [], None) == "admin"
    assert resolve_role(cfg, [], "user") == "user"  # sin mapeos no se sincroniza


# --------------------------------------------------------------------------- con base de datos

@pytest.fixture
def cfg(tmp_path):
    return load_config(tmp_path / "no-existe.json")


def test_create_and_authenticate(db_conn, cfg):
    accounts.create_account(db_conn, username="ana", source="local", password="contraseña-larga")
    user = accounts.authenticate_password(db_conn, cfg, "ana", "contraseña-larga")
    assert user["username"] == "ana" and user["last_login"]
    assert accounts.authenticate_password(db_conn, cfg, "ana", "mala") is None
    assert accounts.authenticate_password(db_conn, cfg, "nadie", "x") is None


@pytest.mark.parametrize("kwargs, message", [
    ({"username": "../x", "source": "local", "password": "contraseña-larga"}, "no válido"),
    ({"username": "x", "source": "local", "password": "corta"}, "al menos"),
    ({"username": "x", "source": "ldap"}, "Origen"),
    ({"username": "x", "source": "entra", "role": "root"}, "Rol"),
])
def test_create_validation(db_conn, kwargs, message):
    with pytest.raises(AccountError, match=message):
        accounts.create_account(db_conn, **kwargs)


def test_entra_username_lowercased(db_conn):
    uid = accounts.create_account(db_conn, username="Juan@Contoso.com", source="entra")
    assert users.get_by_id(db_conn, uid)["username"] == "juan@contoso.com"


def test_last_admin_guard(db_conn):
    a = users.get_by_id(db_conn, accounts.create_account(
        db_conn, username="a", source="entra", role="admin"))
    b = users.get_by_id(db_conn, accounts.create_account(
        db_conn, username="b", source="entra", role="admin"))
    fields = dict(enabled=True, display_name=None, email=None, groups=[], home_path=None)
    accounts.update_account(db_conn, a, b, role="user", **fields)         # b degrada a a
    with pytest.raises(AccountError, match="al menos un administrador"):
        accounts.delete_account(db_conn, users.get_by_id(db_conn, b["id"]), a)
    with pytest.raises(AccountError, match="propia cuenta"):
        accounts.delete_account(db_conn, b, b)


def test_login_with_claims_provisions(db_conn):
    ecfg = {**load_config(None)["auth"]["entra"], "tenant_id": "t1",
            "role_mappings": {"admins": "admin"}}
    claims = {"tid": "t1", "oid": "o1", "preferred_username": "Eva@X.com", "groups": ["ADMINS"]}
    user = accounts.login_with_claims(db_conn, ecfg, claims, ip="1.2.3.4")
    assert user["username"] == "eva@x.com" and user["role"] == "admin" and user["source"] == "entra"
    assert [r["action"] for r in audit.recent(db_conn, 5)] == ["user_provisioned"]
    with pytest.raises(AccountError):
        accounts.login_with_claims(db_conn, ecfg, {**claims, "tid": "otro"})

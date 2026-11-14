"""Grupos: pertenencias manuales y sincronizadas, lista efectiva, migración y acceso a carpetas."""
import sqlite3

import pytest

from storageweb.core import accounts
from storageweb.core import groups as gc
from storageweb.core.storage import available_roots
from storageweb.db import connect, migrate
from storageweb.db import connection
from storageweb.db.repositories import groups as repo
from storageweb.db.repositories import users
from storageweb.providers.entra.method import identity_from_claims
from storageweb.settings import load_config


def _ecfg():
    return {**load_config(None)["auth"]["entra"], "tenant_id": "t1"}


def _login(conn, groups, oid="o1", name="eva@x.com"):
    claims = {"tid": "t1", "oid": oid, "preferred_username": name, "groups": groups}
    return accounts.login_sso(conn, {"auth": {"entra": _ecfg()}}, "entra", identity_from_claims(_ecfg(), claims))


def _eff(conn, uid):
    return gc.split(users.get_by_id(conn, uid)["groups"])


def test_create_validates(db_conn):
    with pytest.raises(gc.GroupError, match="Identificador"):
        gc.create_group(db_conn, name="Con espacio")
    with pytest.raises(gc.GroupError, match="identificador del grupo externo"):
        gc.create_group(db_conn, name="it", source="entra")
    gid = gc.create_group(db_conn, name="RRHH", label="Recursos Humanos")
    group = repo.get_by_id(db_conn, gid)
    assert group["name"] == "rrhh" and group["source"] == "local" and group["external_id"] is None
    with pytest.raises(gc.GroupError, match="Ya existe"):
        gc.create_group(db_conn, name="rrhh")
    gc.create_group(db_conn, name="it", source="entra", external_id="OID-1")
    with pytest.raises(gc.GroupError, match="ya está vinculado"):
        gc.create_group(db_conn, name="it2", source="entra", external_id="oid-1")


def test_sso_login_syncs_and_keeps_manual(db_conn):
    it = repo.get_by_id(db_conn, gc.create_group(db_conn, name="it", source="entra", external_id="oid-it"))
    fin = repo.get_by_id(db_conn, gc.create_group(db_conn, name="finanzas"))
    user = _login(db_conn, ["OID-IT", "otro"])
    assert _eff(db_conn, user["id"]) == {"oid-it", "otro", "it"}
    assert repo.get_membership(db_conn, user["id"], it["id"])["origin"] == "sync"

    gc.add_member(db_conn, fin, user)                        # un admin lo añade a mano
    user = _login(db_conn, [])                               # Entra ya no le da grupos
    assert _eff(db_conn, user["id"]) == {"finanzas"}         # el manual se conserva
    assert repo.get_membership(db_conn, user["id"], it["id"]) is None


def test_manual_membership_wins_and_sync_cannot_be_removed(db_conn):
    it = repo.get_by_id(db_conn, gc.create_group(db_conn, name="it", source="entra", external_id="oid-it"))
    user = _login(db_conn, ["oid-it"])
    with pytest.raises(gc.GroupError, match="se cambia allí"):
        gc.remove_member(db_conn, it, user)
    gc.add_member(db_conn, it, user)
    assert repo.get_membership(db_conn, user["id"], it["id"])["origin"] == "manual"
    _login(db_conn, ["oid-it"])
    assert repo.get_membership(db_conn, user["id"], it["id"])["origin"] == "manual"
    gc.remove_member(db_conn, it, user)                      # sigue en Entra: vuelve como sync
    assert repo.get_membership(db_conn, user["id"], it["id"])["origin"] == "sync"


def test_registering_group_syncs_existing_users(db_conn):
    user = _login(db_conn, ["oid-nuevo"])
    gid = gc.create_group(db_conn, name="nuevo", source="entra", external_id="oid-nuevo")
    assert "nuevo" in _eff(db_conn, user["id"])
    group = repo.get_by_id(db_conn, gid)
    gc.update_group(db_conn, group, label="Nuevo", description="", source="entra", external_id="otro-oid")
    assert "nuevo" not in _eff(db_conn, user["id"])
    gc.update_group(db_conn, repo.get_by_id(db_conn, gid), label="Nuevo", description="", source="entra",
                    external_id="oid-nuevo")
    gc.delete_group(db_conn, repo.get_by_id(db_conn, gid))
    assert _eff(db_conn, user["id"]) == {"oid-nuevo"}


def test_set_manual_groups_creates_local_groups(db_conn):
    uid = accounts.create_account(db_conn, username="ana", source="local", password="contraseña-larga",
                                  groups=["RRHH", "it"])
    assert _eff(db_conn, uid) == {"rrhh", "it"}
    assert repo.get_by_name(db_conn, "rrhh")["source"] == "local"
    gc.set_manual_groups(db_conn, uid, ["it"])
    assert _eff(db_conn, uid) == {"it"}


def test_detected_groups(db_conn):
    _login(db_conn, ["oid-a", "oid-b"])
    _login(db_conn, ["oid-a"], oid="o2", name="luis@x.com")
    gc.create_group(db_conn, name="b", source="entra", external_id="oid-b")
    shares = [{"name": "s", "label": "S", "groups": ["fantasma", "b"], "users": [], "read_only": False}]
    found = {d["id"]: d for d in gc.detected(db_conn, shares)}
    assert set(found) == {"oid-a", "fantasma"}
    assert found["oid-a"]["users"] == 2 and found["oid-a"]["source"] == "entra"
    assert found["fantasma"]["source"] is None and found["fantasma"]["shares"] == ["S"]


def test_share_levels_and_apply_access(tmp_path):
    group = {"name": "it", "external_id": "oid-it"}
    share = {"name": "sw", "label": "SW", "path": str(tmp_path), "read_only": False, "users": [],
             "groups": ["oid-it"], "read_only_groups": []}
    assert gc.share_level(group, share) == "write"
    shares = gc.apply_access([share], group, "sw", "read")
    assert shares[0]["groups"] == ["it"] and shares[0]["read_only_groups"] == ["it"]
    assert gc.share_level(group, shares[0]) == "read"
    assert share["groups"] == ["oid-it"]                     # no modifica el original
    assert gc.apply_access(shares, group, "sw", "none")[0]["groups"] == []
    ro = {**share, "read_only": True}
    assert gc.share_level(group, gc.apply_access([ro], group, "sw", "write")[0]) == "read"
    with pytest.raises(gc.GroupError):
        gc.apply_access(shares, group, "sw", "admin")


def test_storage_read_only_per_group(tmp_path):
    cfg = {"data_dir": str(tmp_path), "storage": {"home_template": str(tmp_path / "{username}"), "shares": [
        {"name": "sw", "label": "SW", "path": str(tmp_path / "sw"), "read_only": False, "users": ["jefa"],
         "groups": ["it", "lectores"], "read_only_groups": ["lectores"]}]}}
    user = {"username": "x", "home_path": None, "groups": "", "role": "user"}

    def mode(**kw):
        roots = {r["name"]: r for r in available_roots({**user, **kw}, cfg)}
        return None if "sw" not in roots else ("ro" if roots["sw"]["read_only"] else "rw")
    assert mode() is None
    assert mode(groups="lectores") == "ro"
    assert mode(groups="lectores,it") == "rw"               # otro grupo le da escritura
    assert mode(username="jefa", groups="lectores") == "rw"  # entra por usuario


def test_migration_004_moves_groups(tmp_path):
    db = str(tmp_path / "v3.db")
    conn = sqlite3.connect(db)
    for version in (1, 2, 3):
        path = next(p for v, p in connection.available_migrations() if v == version)
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version = 3")
    conn.execute("INSERT INTO users (username, source, groups, created_at) VALUES ('ana', 'local', 'it,rrhh', 'x')")
    conn.execute("INSERT INTO users (username, source, groups, created_at) VALUES ('eva', 'entra', 'oid-1', 'x')")
    conn.commit()
    conn.close()
    conn = connect(db)
    assert migrate(conn) == [v for v, _ in connection.available_migrations() if v > 3]
    ana = users.get_by_username(conn, "ana")
    eva = users.get_by_username(conn, "eva")
    assert {g["name"] for g in repo.memberships(conn, ana["id"])} == {"it", "rrhh"}
    assert all(g["origin"] == "manual" for g in repo.memberships(conn, ana["id"]))
    assert eva["external_groups"] == "oid-1" and repo.memberships(conn, eva["id"]) == []
    gc.refresh_user(conn, ana["id"])
    assert users.get_by_id(conn, ana["id"])["groups"] == "it,rrhh"


def test_builtin_admins_group(db_conn):
    admins = repo.get_builtin(db_conn, gc.ADMINS_GROUP)
    assert admins is not None and gc.label(admins) == "Administradores"
    a = users.get_by_id(db_conn, accounts.create_account(db_conn, username="a", source="entra", role="admin"))
    b = users.get_by_id(db_conn, accounts.create_account(db_conn, username="b", source="entra"))
    assert [m["username"] for m in gc.members(db_conn, admins)] == ["a"]
    assert repo.list_all(db_conn)[0]["members"] == 1 and repo.list_all(db_conn)[0]["builtin"] == 1

    with pytest.raises(gc.GroupError, match="no se puede eliminar"):
        gc.delete_group(db_conn, admins)
    with pytest.raises(gc.GroupError, match="no se puede cambiar"):
        gc.update_group(db_conn, admins, label="x", description="", source="local", external_id=None)
    with pytest.raises(gc.GroupError, match="cambia el rol"):
        gc.set_manual_groups(db_conn, b["id"], ["admins"])

    gc.add_member(db_conn, admins, b)                        # añadir = dar el rol
    assert users.get_by_id(db_conn, b["id"])["role"] == "admin"
    with pytest.raises(gc.GroupError, match="ti mismo"):
        gc.remove_member(db_conn, admins, a, actor=a)
    gc.remove_member(db_conn, admins, a, actor=b)            # quitar = retirar el rol
    assert users.get_by_id(db_conn, a["id"])["role"] == "user"
    with pytest.raises(gc.GroupError, match="al menos un administrador"):
        gc.remove_member(db_conn, admins, users.get_by_id(db_conn, b["id"]), actor=a)
    assert {m["name"] for m in gc.memberships(db_conn, users.get_by_id(db_conn, b["id"]))} == {"admins"}


def test_admins_group_gives_share_access(tmp_path):
    cfg = {"data_dir": str(tmp_path), "storage": {"home_template": str(tmp_path / "{username}"), "shares": [
        {"name": "it", "label": "IT", "path": str(tmp_path / "it"), "read_only": False, "users": [],
         "groups": ["admins"], "read_only_groups": []}]}}
    base = {"username": "x", "home_path": None, "groups": ""}
    assert "it" in {r["name"] for r in available_roots({**base, "role": "admin"}, cfg)}
    assert "it" not in {r["name"] for r in available_roots({**base, "role": "user"}, cfg)}


def test_migration_005_on_database_already_at_004(tmp_path):
    """Una BD que ya aplicó la 004 (sin grupos de serie) recibe «admins»; un grupo local homónimo se renombra."""
    db = str(tmp_path / "v4.db")
    conn = sqlite3.connect(db)
    for version, path in connection.available_migrations():
        if version <= 4:
            conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version = 4")
    conn.execute("INSERT INTO groups (name, label, source, created_at) VALUES ('admins', 'admins', 'local', 'x')")
    conn.commit()
    conn.close()
    conn = connect(db)
    assert 5 in migrate(conn)
    rows = {r["name"]: r["builtin"] for r in conn.execute("SELECT name, builtin FROM groups")}
    assert rows == {"admins": 1, "admins-local": 0}

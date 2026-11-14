import json

import pytest

from storageweb.settings import ConfigError, ensure_secret_key, load_config, mask_secrets


def _cfg(tmp_path, data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_defaults_without_file(tmp_path):
    cfg = load_config(tmp_path / "no-existe.json")
    assert cfg["default_locale"] == "en"
    assert cfg["server"]["port"] == 8080
    assert cfg["auth"]["local"]["enabled"] is True
    assert cfg["auth"]["entra"]["provider"] == "oauth2"


def test_relative_paths_resolved_from_config_dir(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"data_dir": "datos",
                                      "storage": {"home_template": "h/{username}",
                                                  "shares": [{"name": "s", "path": "comp"}]}}))
    assert cfg["data_dir"] == str(tmp_path / "datos")
    assert cfg["database"] == str(tmp_path / "datos" / "storageweb.db")
    assert cfg["storage"]["home_template"].startswith(str(tmp_path))
    assert cfg["storage"]["home_template"].endswith("{username}")
    assert cfg["storage"]["shares"][0]["path"] == str(tmp_path / "comp")


def test_share_defaults_and_lowercase(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"storage": {"shares": [
        {"name": "Equipo", "path": "x", "users": ["Ana"], "groups": ["RRHH"]}]}}))
    share = cfg["storage"]["shares"][0]
    assert share["label"] == "Equipo" and share["read_only"] is False
    assert share["users"] == ["ana"] and share["groups"] == ["rrhh"]


@pytest.mark.parametrize("shares", [
    [{"name": "con espacio", "path": "x"}],
    [{"name": "home", "path": "x"}],
    [{"name": "a", "path": "x"}, {"name": "A", "path": "y"}],
    [{"name": "sinpath"}],
])
def test_invalid_shares(tmp_path, shares):
    with pytest.raises(ConfigError):
        load_config(_cfg(tmp_path, {"storage": {"shares": shares}}))


def test_home_template_requires_placeholder(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_cfg(tmp_path, {"storage": {"home_template": "/srv/homes"}}))


def test_invalid_json(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{no json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_entra_requires_credentials(tmp_path):
    with pytest.raises(ConfigError, match="client_secret"):
        load_config(_cfg(tmp_path, {"auth": {"entra": {"enabled": True, "tenant_id": "t",
                                                       "client_id": "c"}}}))


def test_entra_oauth2_custom_endpoints_without_tenant(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"auth": {"entra": {
        "enabled": True, "client_id": "c", "client_secret": "s",
        "authorize_url": "https://idp/auth", "token_url": "https://idp/token", "issuer": "https://idp"}}}))
    assert cfg["auth"]["entra"]["enabled"]


def test_entra_msal_requires_tenant(tmp_path):
    with pytest.raises(ConfigError, match="tenant_id"):
        load_config(_cfg(tmp_path, {"auth": {"entra": {
            "enabled": True, "provider": "msal", "client_id": "c", "client_secret": "s",
            "authorize_url": "https://idp/auth", "token_url": "https://idp/token", "issuer": "https://idp"}}}))


def test_entra_invalid_provider(tmp_path):
    with pytest.raises(ConfigError, match="provider"):
        load_config(_cfg(tmp_path, {"auth": {"entra": {"provider": "saml"}}}))


def test_secret_key_generated_once(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"data_dir": "d"}))
    key1 = ensure_secret_key(cfg)
    key2 = ensure_secret_key(cfg)
    assert key1 == key2 and len(key1) == 64
    assert (tmp_path / "d" / "secret_key").read_text().strip() == key1


def test_secret_key_from_config(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"secret_key": "fija"}))
    assert ensure_secret_key(cfg) == "fija"


def test_overrides_replace_sections(tmp_path):
    p = _cfg(tmp_path, {"app_name": "Fichero", "storage": {"shares": [{"name": "a", "path": "x"}]},
                        "auth": {"entra": {"client_secret": "del-fichero", "role_mappings": {"G1": "admin"}}}})
    cfg = load_config(p, overrides={"app_name": "Web", "storage": {"shares": []},
                                    "auth": {"entra": {"client_secret": "", "role_mappings": {}}},
                                    "server": {"port": 1}})
    assert cfg["app_name"] == "Web"
    assert cfg["storage"]["shares"] == []
    assert cfg["auth"]["entra"]["role_mappings"] == {}          # se pueden borrar mapeos
    assert cfg["auth"]["entra"]["client_secret"] == "del-fichero"  # secreto vacío = el del fichero
    assert cfg["server"]["port"] == 8080                       # server no es editable desde la web


@pytest.mark.parametrize("entra", [
    {"default_role": "superuser"},
    {"role_mappings": {"g": "root"}},
    {"role_mappings": ["no", "dict"]},
    {"timeout_seconds": 0},
])
def test_invalid_entra_roles(tmp_path, entra):
    with pytest.raises(ConfigError):
        load_config(_cfg(tmp_path, {"auth": {"entra": entra}}))


def test_role_mapping_keys_lowercased(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"auth": {"entra": {"role_mappings": {"StorageWeb.Admin": "admin"}}}}))
    assert cfg["auth"]["entra"]["role_mappings"] == {"storageweb.admin": "admin"}


def test_at_least_one_login_method(tmp_path):
    with pytest.raises(ConfigError, match="al menos un"):
        load_config(_cfg(tmp_path, {"auth": {"local": {"enabled": False}}}))


def test_permissions_normalized(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"permissions": {"user": {"delete": 1, "otro": True}}}))
    # Los permisos no indicados toman el valor por defecto; las claves desconocidas se ignoran
    assert cfg["permissions"]["user"] == {"upload": True, "download": True, "mkdir": True,
                                          "rename": False, "delete": True}


def test_default_user_permissions(tmp_path):
    perms = load_config(tmp_path / "nada.json")["permissions"]["user"]
    assert perms["upload"] and perms["download"] and not perms["delete"] and not perms["rename"]


def test_mask_secrets(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"auth": {"entra": {"client_secret": "s3cr3t"}}}))
    assert mask_secrets(cfg)["auth"]["entra"]["client_secret"] == "********"
    assert cfg["auth"]["entra"]["client_secret"] == "s3cr3t"


def test_overrides_merge_over_file_field_by_field(tmp_path):
    """Los ajustes web se combinan sobre config.json: lo que no cambian sigue viniendo del fichero."""
    p = _cfg(tmp_path, {"auth": {"entra": {"tenant_id": "del-fichero", "client_id": "c"}}})
    cfg = load_config(p, overrides={"auth": {"entra": {"client_id": "web"}}})
    assert cfg["auth"]["entra"]["tenant_id"] == "del-fichero" and cfg["auth"]["entra"]["client_id"] == "web"


def test_diff_and_paths_helpers():
    from storageweb.settings import diff_overrides, drop_path, leaf_paths

    base = {"app_name": "A", "auth": {"entra": {"tenant_id": "t", "role_mappings": {"g": "admin"}}}}
    new = {"app_name": "A", "auth": {"entra": {"tenant_id": "x", "role_mappings": {}}}}
    diff = diff_overrides(base, new)
    assert diff == {"auth": {"entra": {"tenant_id": "x", "role_mappings": {}}}}
    assert leaf_paths(diff) == {"auth.entra.tenant_id", "auth.entra.role_mappings"}
    assert drop_path(diff, "auth.entra.tenant_id") == {"auth": {"entra": {"role_mappings": {}}}}
    assert drop_path({"auth": {"entra": {"tenant_id": "x"}}}, "auth.entra.tenant_id") == {}


def test_runtime_saves_only_differences(tmp_path, db_conn):
    from storageweb.settings import RuntimeSettings, read_config_file, runtime_view

    p = _cfg(tmp_path, {"app_name": "Fichero"})
    rt = RuntimeSettings(*read_config_file(p))
    view = runtime_view(rt.current(db_conn))
    view["security"]["lockout_minutes"] = 42
    assert rt.save(db_conn, view, "root") == {"security": {"lockout_minutes": 42}}
    assert rt.changed_paths(db_conn) == {"security.lockout_minutes"}
    rt.reset_path(db_conn, "security.lockout_minutes", "root")
    assert rt.overrides(db_conn) == {} and rt.changed_paths(db_conn) == set()

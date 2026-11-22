
import pytest

from storageweb.settings import ConfigError, ensure_secret_key, load_config, mask_secrets
from tests.helpers import config_file


def _cfg(tmp_path, data):
    p = config_file(tmp_path, data)
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


S3 = {"name": "s3", "type": "s3", "bucket": "b", "secret_key": "SECRETO"}


@pytest.mark.parametrize("storage, match", [
    ({"locations": [{"name": "x", "type": "gopher"}]}, "tipo"),
    ({"locations": [{"name": "x", "type": "s3"}]}, "bucket"),
    ({"locations": [{"name": "x", "type": "smb", "server": "s"}]}, "share"),
    ({"locations": [S3, S3]}, "repetido"),
    ({"locations": [{**S3, "endpoint_url": "minio:9000"}]}, "https://"),
    ({"locations": [S3], "home_location": "otra"}, "home_location"),
    ({"locations": [S3], "shares": [{"name": "d", "location": "otra", "path": "d"}]}, "no existe"),
    ({"locations": [S3], "shares": [{"name": "d", "location": "s3", "path": "../fuera"}]}, "relativa"),
    ({"locations": [S3], "home_location": "s3", "home_template": "C:/homes/{username}"}, "relativa"),
])
def test_invalid_locations(tmp_path, storage, match):
    with pytest.raises(ConfigError, match=match):
        load_config(_cfg(tmp_path, {"storage": storage}))


def test_locations_normalized_and_masked(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"storage": {
        "locations": [S3, {"name": "nas", "type": "smb", "server": "nas", "share": "f", "path": "\\a\\b\\",
                           "password": "CLAVE"}],
        "home_location": "nas", "home_template": "/homes/{username}/",
        "shares": [{"name": "d", "location": "s3", "path": "/docs/"}, {"name": "l", "path": "local"}]}}))
    st = cfg["storage"]
    assert st["locations"][1]["path"] == "a/b" and st["locations"][1]["port"] == 445
    assert st["home_template"] == "homes/{username}"
    assert st["shares"][0]["path"] == "docs" and st["shares"][1]["location"] == ""
    masked = str(mask_secrets(cfg))
    assert "SECRETO" not in masked and "CLAVE" not in masked


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


def test_file_wins_over_web_settings(tmp_path):
    """config.json gana sobre los ajustes web campo a campo; lo que no fija lo deciden la web o los predeterminados."""
    p = _cfg(tmp_path, {"app_name": "Fichero", "auth": {"entra": {"role_mappings": {"G1": "admin"}}}})
    cfg = load_config(p, overrides={"app_name": "Web", "storage": {"shares": []}, "default_locale": "es",
                                    "auth": {"entra": {"role_mappings": {}, "client_id": "web"}},
                                    "server": {"port": 1}})
    assert cfg["app_name"] == "Fichero"
    assert cfg["auth"]["entra"]["role_mappings"] == {"g1": "admin"}
    assert cfg["default_locale"] == "es" and cfg["auth"]["entra"]["client_id"] == "web"
    assert cfg["server"]["port"] == 8080                       # server no es editable desde la web


@pytest.mark.parametrize("entra", [
    {"default_role": "Super User!"},             # la clave de un rol propio: minúsculas, números, - y _
    {"role_mappings": {"g": "Root Admin"}},
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
                                          "rename": False, "delete": True, "edit": False, "share": False}


def test_default_user_permissions(tmp_path):
    perms = load_config(tmp_path / "nada.json")["permissions"]["user"]
    assert perms["upload"] and perms["download"] and not perms["delete"] and not perms["rename"]


def test_mask_secrets(tmp_path):
    cfg = load_config(_cfg(tmp_path, {"auth": {"entra": {"client_secret": "s3cr3t"}}}))
    assert mask_secrets(cfg)["auth"]["entra"]["client_secret"] == "********"
    assert cfg["auth"]["entra"]["client_secret"] == "s3cr3t"


def test_environment_wins_over_everything(tmp_path):
    p = _cfg(tmp_path, {"app_name": "Fichero", "server": {"port": 9000}})
    env = {"STORAGEWEB_APP_NAME": "Entorno", "STORAGEWEB_PORT": "7000", "STORAGEWEB_AUTH__ENTRA__SCOPES": "a, b",
           "STORAGEWEB_SECURITY__IPBAN_ENABLED": "false", "STORAGEWEB_STORAGE__SHARES": '[{"name": "x", "path": "/x"}]',
           "STORAGEWEB_LANG": "es", "STORAGEWEB_CONFIG": "no-cuenta"}
    cfg = load_config(p, overrides={"app_name": "Web"}, environ=env)
    assert cfg["app_name"] == "Entorno" and cfg["server"]["port"] == 7000
    assert cfg["auth"]["entra"]["scopes"] == ["a", "b"] and cfg["security"]["ipban_enabled"] is False
    assert [s["name"] for s in cfg["storage"]["shares"]] == ["x"]


@pytest.mark.parametrize("name, value", [("STORAGEWEB_SERVER__PORT", "mucho"),
                                         ("STORAGEWEB_SECURITY__API_TOKENS", "quizá"),
                                         ("STORAGEWEB_STORAGE__SHARES", "[roto")])
def test_invalid_environment_values(tmp_path, name, value):
    with pytest.raises(ConfigError, match=name):
        load_config(tmp_path / "nada.json", environ={name: value})


def test_env_names():
    from storageweb.settings import env_name, setting_paths

    assert env_name("auth.entra.client_id") == "STORAGEWEB_AUTH__ENTRA__CLIENT_ID"
    assert env_name("app_name") == "STORAGEWEB_APP_NAME"
    paths = setting_paths()
    assert "storage.shares" in paths and "auth.entra.role_mappings" in paths and "auth.entra" not in paths


def test_diff_and_paths_helpers():
    from storageweb.settings import diff_overrides, drop_path, leaf_paths

    base = {"app_name": "A", "auth": {"entra": {"tenant_id": "t", "role_mappings": {"g": "admin"}}}}
    new = {"app_name": "A", "auth": {"entra": {"tenant_id": "x", "role_mappings": {}}}}
    diff = diff_overrides(base, new)
    assert diff == {"auth": {"entra": {"tenant_id": "x", "role_mappings": {}}}}
    assert leaf_paths(diff) == {"auth.entra.tenant_id", "auth.entra.role_mappings"}
    assert drop_path(diff, "auth.entra.tenant_id") == {"auth": {"entra": {"role_mappings": {}}}}
    assert drop_path({"auth": {"entra": {"tenant_id": "x"}}}, "auth.entra.tenant_id") == {}


def test_runtime_saves_only_differences_from_defaults(tmp_path, db_conn):
    from storageweb.settings import RuntimeSettings, read_config_file, runtime_view

    p = _cfg(tmp_path, {"app_name": "Fichero"})
    rt = RuntimeSettings(*read_config_file(p))
    view = runtime_view(rt.current(db_conn))
    view["security"]["lockout_minutes"] = 42
    view["app_name"] = "Intento"                      # bloqueado por config.json: no se guarda
    assert rt.save(db_conn, view, "root") == {"security": {"lockout_minutes": 42}}
    assert rt.current(db_conn)["app_name"] == "Fichero"
    assert rt.origins(db_conn) == {"security.lockout_minutes": "web", "app_name": "file"}
    assert rt.modified_paths(db_conn) == {"security.lockout_minutes", "app_name"}
    rt.reset_path(db_conn, "security.lockout_minutes", "root")     # vuelve al predeterminado
    assert rt.overrides(db_conn) == {} and rt.current(db_conn)["security"]["lockout_minutes"] == 15
    with pytest.raises(ConfigError, match="config.json"):
        rt.reset_path(db_conn, "app_name", "root")


def test_runtime_locks_and_strict_save(tmp_path, db_conn):
    from storageweb.settings import RuntimeSettings, read_config_file, runtime_view

    p = _cfg(tmp_path, {"storage": {"shares": []}})
    rt = RuntimeSettings(*read_config_file(p), env_cfg={"auth": {"entra": {"client_id": "env"}}})
    # Las carpetas de config.json no bloquean la lista: se bloquea cada una (su «origin»; ver test_entities)
    assert rt.locked() == {"auth.entra.client_id": "env"}
    assert rt.lock_of("storage.shares") is None and rt.lock_of("auth.entra.client_id") == "env"
    assert rt.lock_of("auth.entra.tenant_id") is None
    view = runtime_view(rt.current(db_conn))
    view["auth"]["entra"]["client_id"] = "otro"
    with pytest.raises(ConfigError, match="STORAGEWEB_AUTH__ENTRA__CLIENT_ID"):
        rt.save(db_conn, view, "root", strict=True)
    rt.save(db_conn, view, "root")                     # sin strict, el campo bloqueado se ignora
    assert rt.current(db_conn)["auth"]["entra"]["client_id"] == "env" and rt.overrides(db_conn) == {}

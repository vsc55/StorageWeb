"""Métodos de inicio de sesión: se descubren solos y todo lo general sale de ``providers.AuthMethod``.

Los métodos ``llave`` (contraseña) y ``demo`` (SSO) se definen aquí y funcionan en la configuración,
el login, el SSO, los grupos, el Resumen y la página de ajustes sin tocar código general.
"""
import copy
import json

import pytest

from storageweb import providers
from storageweb.core import accounts, alerts
from storageweb.core import groups as gc
from storageweb.db.repositories import users
from storageweb.providers import AuthDenied, AuthMethod, Identity, LoginButton, Notice
from storageweb.settings import ConfigError, auth_methods, defaults, fields, load_config, mask_secrets
from storageweb.settings.auth_methods import AuthConfig
from storageweb.settings.fields import Field


def _validate_llave(section, cfg):
    if section["realm"] == "malo":
        raise ConfigError("realm no válido", "auth.llave.realm")


class LlaveMethod(AuthMethod):
    """Contraseña contra un «servicio» ficticio: vale ``secreto-<usuario>``; da de alta y trae grupos."""
    key = "llave"
    label = "Llave"
    description = "Servicio de llaves de prueba"
    order = 40
    password = True
    provisions = True
    external_groups = True
    group_hint = "Grupos del servicio de llaves."
    group_id_help = "Llave: nombre del grupo."
    config = AuthConfig(
        key="llave",
        defaults={"enabled": False, "realm": "", "api_key": "", "groups": [], "timeout": 5},
        fields={"enabled": Field(doc="Activar Llave.", label="Llave", page="auth"),
                "realm": Field(doc="Reino.", label="Reino", page="auth"),
                "api_key": Field(doc="Clave (secreta).", label="Clave", page="auth"),
                "groups": Field(doc="Grupos que da.", label="Grupos", page="auth"),
                "timeout": Field(doc="Espera.", label="Espera", page="auth")},
        validate=_validate_llave, secrets=("api_key",), order=40)

    def verify(self, section, user, username, password):
        if password != f"secreto-{username}":
            return None
        return Identity(username=username, groups=list(section["groups"]))

    def notices(self, section):
        return [Notice("warn", "llave_realm", "Llave sin reino", "", "Configurar")] if not section["realm"] else []


class DemoMethod(AuthMethod):
    """SSO ficticio: el «proveedor» devuelve la identidad que viene en el parámetro ``who``."""
    key = "demo"
    label = "Demo"
    order = 50
    sso = True
    external_groups = True
    config = AuthConfig(key="demo", defaults={"enabled": False, "auto_provision": True, "default_role": "user",
                                              "role_mappings": {}, "sync_role_on_login": True},
                        fields={"enabled": Field(doc="Activar Demo.", label="Demo", page="auth"),
                                "auto_provision": Field(doc="Alta automática.", page="auth"),
                                "default_role": Field(doc="Rol.", page="auth"),
                                "role_mappings": Field(doc="Mapeo.", page="auth"),
                                "sync_role_on_login": Field(doc="Sincronizar rol.", page="auth")},
                        leaf=("role_mappings",), order=50)

    def login_button(self, section):
        return LoginButton("Entrar con Demo", "btn-demo")

    def begin(self, section, redirect_uri):
        return f"https://demo.example/authorize?back={redirect_uri}", {"state": "s1"}

    def complete(self, section, flow, args):
        if args.get("who") == "intruso":
            raise AuthDenied("No puedes entrar.", "denied")
        return Identity(username=args["who"], external_id=f"id-{args['who']}", groups=["demo-equipo"])


@pytest.fixture
def extra_methods():
    """Registra los dos métodos de prueba y lo deja todo como estaba al terminar."""
    saved = (dict(providers._METHODS), dict(auth_methods._CONFIGS), copy.deepcopy(defaults.DEFAULTS["auth"]),
             dict(fields.FIELDS), list(defaults.SECRET_FIELDS), set(defaults.SECRET_PATHS),
             list(defaults.LEAF_PATHS))
    providers.register(LlaveMethod)
    providers.register(DemoMethod)
    yield
    providers._METHODS.clear()
    providers._METHODS.update(saved[0])
    auth_methods._CONFIGS.clear()
    auth_methods._CONFIGS.update(saved[1])
    defaults.DEFAULTS["auth"].clear()
    defaults.DEFAULTS["auth"].update(saved[2])
    fields.FIELDS.clear()
    fields.FIELDS.update(saved[3])
    defaults.SECRET_FIELDS[:] = saved[4]
    defaults.SECRET_PATHS.clear()
    defaults.SECRET_PATHS.update(saved[5])
    defaults.LEAF_PATHS[:] = saved[6]


def _cfg(tmp_path, auth):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"auth": auth}), encoding="utf-8")
    return load_config(p)


def test_builtin_methods_are_discovered():
    assert [m.key for m in providers.methods()] == ["local", "pam", "entra"]
    assert list(defaults.DEFAULTS["auth"]) == ["local", "pam", "entra"]
    assert "auth.entra.client_secret" in defaults.SECRET_PATHS
    assert ("auth", "entra", "role_mappings") in defaults.LEAF_PATHS
    assert fields.FIELDS["auth.pam.service"].label
    assert providers.discover() == providers.methods()  # idempotente


def test_new_method_in_config_and_accounts(extra_methods, tmp_path, db_conn):
    assert list(defaults.DEFAULTS["auth"])[-2:] == ["llave", "demo"]
    with pytest.raises(ConfigError, match="realm"):
        _cfg(tmp_path, {"llave": {"realm": "malo"}})
    cfg = _cfg(tmp_path, {"llave": {"enabled": True, "api_key": "K", "groups": ["equipo"]}})
    assert cfg["auth"]["llave"]["timeout"] == 5
    assert "K" not in json.dumps(mask_secrets(cfg))

    # Contraseña: da de alta en el primer inicio de sesión y sincroniza sus grupos
    assert accounts.authenticate_password(db_conn, cfg, "ana", "mala") is None
    user = accounts.authenticate_password(db_conn, cfg, "ana", "secreto-ana")
    assert user["source"] == "llave" and user["role"] == "none" and "equipo" in gc.split(user["groups"])
    assert "llave" in gc.group_sources() and accounts.source_labels()["llave"] == "Llave"
    assert not accounts.stores_password("llave")

    # SSO: identidad del proveedor → cuenta nueva; AuthDenied → AccountError
    cfg["auth"]["demo"]["enabled"] = True
    eva, _identity = accounts.complete_sso(db_conn, cfg, "demo", {}, {"who": "eva"})
    assert eva["source"] == "demo" and eva["external_id"] == "id-eva"
    with pytest.raises(accounts.AccountError, match="No puedes"):
        accounts.complete_sso(db_conn, cfg, "demo", {}, {"who": "intruso"})
    assert users.get_by_username(db_conn, "intruso") is None

    # Aviso del Resumen: lo da el método
    found = alerts.collect(cfg, {"data_dir": str(tmp_path)}, {})
    assert [a for a in found if a["key"] == "llave_realm"][0]["page"] == "auth"


def test_new_method_in_the_web(extra_methods, make_app):
    from tests.helpers import add_user, get_csrf, login
    from storageweb.web.context import settings

    app = make_app({"auth": {"llave": {"enabled": True}, "demo": {"enabled": True}}})
    client = app.test_client()
    page = client.get("/login").get_data(as_text=True)
    assert "Entrar con Demo" in page and 'name="password"' in page

    # SSO genérico: /auth/demo/login → proveedor → /auth/demo/callback
    r = client.get("/auth/demo/login")
    assert r.location.startswith("https://demo.example/authorize?back=") and "/auth/demo/callback" in r.location
    r = client.get("/auth/demo/callback?who=eva")
    assert r.status_code == 302 and client.get("/f/home/").status_code == 200
    assert client.get("/auth/nada/login").status_code == 404

    # Ajustes: tarjeta genérica (sin plantilla propia) con sus campos, y se guardan con el lector genérico
    add_user(app, "root", role="admin")
    admin = app.test_client()
    login(admin, "root")
    html = admin.get("/admin/settings/auth").get_data(as_text=True)
    for name in ("llave_enabled", "llave_realm", "llave_groups", "llave_timeout", "demo_enabled"):
        assert f'name="{name}"' in html
    assert 'type="password" name="llave_api_key"' in html
    token = get_csrf(admin, "/admin/settings/auth")
    form = {"_csrf": token, "local_enabled": "on", "entra_provider": "oauth2", "entra_timeout_seconds": "15",
            "entra_directory_sync_minutes": "60", "entra_secret_months": "24", "entra_secret_warn_days": "30",
            "password_min_length": "10",
            "llave_enabled": "on", "llave_realm": "casa", "llave_groups": "a, b", "llave_timeout": "9",
            "llave_api_key": "NUEVA", "demo_enabled": "on"}
    admin.post("/admin/settings/auth", data=form)
    with app.app_context():
        llave = settings()["auth"]["llave"]
    assert (llave["realm"], llave["groups"], llave["timeout"], llave["api_key"]) == ("casa", ["a", "b"], 9, "NUEVA")
    admin.post("/admin/settings/auth", data={**form, "llave_api_key": ""})
    with app.app_context():
        assert settings()["auth"]["llave"]["api_key"] == "NUEVA"  # secreto vacío: se conserva
    groups_page = admin.get("/admin/groups/new").get_data(as_text=True)
    assert 'value="llave"' in groups_page and "Grupos del servicio de llaves." in groups_page

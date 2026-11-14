"""Tipos de ubicación: se descubren solos y todo lo general (cargador, web, referencia) sale del esquema.

El tipo ``memoria`` de este fichero demuestra que un tipo nuevo no necesita tocar código general: basta
con una subclase de RemoteBackend con su ``schema``.
"""
from pathlib import Path

import pytest

from storageweb.core import backends, locations
from storageweb.core.backends.s3 import S3Backend
from storageweb.core.backends.smb import SMBBackend
from storageweb.settings import ConfigError, load_config, location_types, mask_secrets
from storageweb.settings.location_types import LocationSchema, Option

from tests.fakes import FakeS3


class MemoryBackend(backends.RemoteBackend):
    """Un tipo inventado: guarda en una carpeta local, pero entra por el mismo camino que S3 o SMB."""

    schema = LocationSchema(
        kind="memoria", label="Memoria (pruebas)", short_label="MEM", doc="Tipo de prueba.",
        place_title="Almacén", extra="",
        options=(Option("almacen", "Almacén", "Nombre del almacén.", required=True),
                 Option("cuota", "Cuota", "Puerto ficticio.", kind="port", default=1234),
                 Option("token", "Token", "Secreto.", kind="secret", section="credentials")))

    @classmethod
    def connect(cls, location):
        return {"conectado": location["almacen"]}

    @classmethod
    def create(cls, client, location, base, staging):
        backend = backends.LocalBackend(Path(staging) / location["almacen"] / base, staging)
        backend.client = client
        return backend

    @classmethod
    def address(cls, location, path=""):
        return f"mem://{location['almacen']}/{path}".rstrip("/")


@pytest.fixture
def memoria(monkeypatch):
    monkeypatch.setattr(backends, "TYPES", dict(backends.TYPES))
    monkeypatch.setattr(backends, "CLIENT_FACTORIES", dict(backends.CLIENT_FACTORIES))
    monkeypatch.setattr(location_types, "_SCHEMAS", dict(location_types._SCHEMAS))
    backends.register(MemoryBackend)
    backends.clear_clients()
    yield MemoryBackend
    backends.clear_clients()


def _cfg(tmp_path, storage):
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"storage": {"home_template": "h/{username}", **storage}}), encoding="utf-8")
    return p


def test_builtin_types_are_discovered():
    assert backends.TYPES["s3"] is S3Backend and backends.TYPES["smb"] is SMBBackend
    assert {"s3", "smb"} <= set(location_types.kinds())
    assert backends.discover() is backends.TYPES  # idempotente
    assert location_types.get("s3").secrets == ("secret_key",)
    assert location_types.get("smb").secrets == ("password",)


def test_new_type_needs_no_general_code(memoria, tmp_path):
    # Cargador: valida con el esquema (obligatorias, puerto, valores por defecto) y oculta los secretos
    with pytest.raises(ConfigError, match="almacen"):
        load_config(_cfg(tmp_path, {"locations": [{"name": "m", "type": "memoria"}]}))
    with pytest.raises(ConfigError, match="cuota"):
        load_config(_cfg(tmp_path, {"locations": [{"name": "m", "type": "memoria", "almacen": "a", "cuota": "x"}]}))
    cfg = load_config(_cfg(tmp_path, {"locations": [{"name": "m", "type": "memoria", "almacen": "a", "token": "T"}],
                                      "shares": [{"name": "d", "location": "m", "path": "docs"}]}))
    loc = cfg["storage"]["locations"][0]
    assert loc["cuota"] == 1234 and loc["label"] == "m"
    assert "T" not in str(mask_secrets(cfg)["storage"]["locations"])

    # Core: backend, dirección y formulario
    backend = backends.backend_for(loc, "docs", tmp_path)
    assert backend.client == {"conectado": "a"}
    assert locations.describe(loc, "docs") == "mem://a/docs"
    edited = locations.from_form({"label": "M", "almacen": "b", "cuota": "9", "token": ""}, loc)
    assert edited["token"] == "T" and edited["almacen"] == "b"
    assert locations.blank("memoria") == {"name": "", "label": "", "type": "memoria", "almacen": "",
                                         "cuota": 1234, "token": ""}

    # Referencia generada
    import importlib.util
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("gen_docs", root / "tools" / "gen_docs.py")
    gen_docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_docs)
    text = gen_docs.render_location_types()
    assert "### `memoria`: MEM" in text and "| `cuota` | puerto | `1234` |" in text


def test_new_type_in_the_admin(memoria, make_app):
    from tests.helpers import add_user, get_csrf, login
    from storageweb.web.context import settings

    app = make_app()
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    index = client.get("/admin/storage/").get_data(as_text=True)
    assert "Nueva ubicación MEM" in index
    page = client.get("/admin/storage/new?type=memoria").get_data(as_text=True)
    assert 'name="almacen"' in page and 'name="cuota"' in page and 'type="password" name="token"' in page
    assert "Almacén" in page
    token = get_csrf(client, "/admin/storage/")
    r = client.post("/admin/storage/new", data={"_csrf": token, "type": "memoria", "name": "m", "label": "",
                                                "almacen": "a", "cuota": "1234", "token": "T"})
    assert r.status_code == 302
    with app.app_context():
        assert settings()["storage"]["locations"][0]["almacen"] == "a"
    assert "mem://a" in client.get("/admin/storage/").get_data(as_text=True)
    assert client.get("/admin/storage/new?type=nada").status_code == 404


def test_s3_schema_matches_the_backend(tmp_path):
    loc = location_types.get("s3").normalize({"bucket": "b", "prefix": "/p/"}, "s3")
    backend = S3Backend.create(FakeS3("b"), loc, "docs", tmp_path)
    assert backend.prefix == "p/docs" and S3Backend.address(loc, "docs") == "s3://b/p/docs"

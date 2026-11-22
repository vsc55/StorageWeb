"""Sistema → Carpetas del servidor (``storage.allowed_folders``): en qué carpetas del disco puede haber carpetas
compartidas y personales. Se comprueba al guardar (ajustes, carpetas compartidas, cuentas, CLI), al abrir la carpeta
(una que ya estaba fuera no se abre) y en el selector de rutas (solo lista dentro)."""
from __future__ import annotations

import json
import os

import pytest

from storageweb.core import accounts, pathpicker, storage
from storageweb.core.backends import UnavailableBackend
from storageweb.db.repositories import users
from storageweb.settings import ConfigError, server_paths
from storageweb.settings.loader import normalize
from storageweb.web.context import get_db, settings
from tests.helpers import U, add_user, page_form, settings_form, visible, signed_in


def test_inside_compares_the_real_path(tmp_path):
    base = tmp_path / "datos"
    (base / "a").mkdir(parents=True)
    (tmp_path / "datos-otro").mkdir()
    allowed = [str(base)]
    assert server_paths.allowed_path(str(base), allowed)
    assert server_paths.allowed_path(str(base / "a" / "aún-no-existe"), allowed)
    assert not server_paths.allowed_path(str(tmp_path / "datos-otro"), allowed)       # no basta con el prefijo
    assert not server_paths.allowed_path(str(base / ".." / "datos-otro"), allowed)
    assert server_paths.allowed_path("/donde/sea", [])                                 # sin lista, cualquiera
    if os.name == "nt":
        assert server_paths.allowed_path(str(base).upper(), allowed)
    try:
        os.symlink(tmp_path / "datos-otro", base / "enlace", target_is_directory=True)
    except OSError:
        pytest.skip("sin permiso para crear enlaces simbólicos")
    assert not server_paths.allowed_path(str(base / "enlace"), allowed)              # el enlace sale de ella
    assert not server_paths.allowed_path(str(base / "enlace" / "x"), allowed)


def _normalize(tmp_path, storage_cfg):
    return normalize({"storage": {"home_template": str(tmp_path / "homes" / "{username}"), **storage_cfg}},
                     tmp_path / "config.json")


def test_saving_checks_the_folders(tmp_path):
    base = str(tmp_path / "datos")
    cfg = _normalize(tmp_path, {"allowed_folders": [str(tmp_path / "homes"), base, base + os.sep, "  "],
                                "shares": [{"name": "obra", "path": str(tmp_path / "datos" / "obra")}]})
    assert cfg["storage"]["allowed_folders"] == [str(tmp_path / "homes"), base]       # sin repetir ni vacías
    assert _normalize(tmp_path, {"allowed_folders": f"relativa\n{tmp_path / 'homes'}"})["storage"][
        "allowed_folders"] == [str(tmp_path / "relativa"), str(tmp_path / "homes")]   # respecto al config.json
    with pytest.raises(ConfigError) as exc:
        _normalize(tmp_path, {"allowed_folders": [str(tmp_path / "homes")],
                              "shares": [{"name": "obra", "path": str(tmp_path / "fuera")}]})
    assert exc.value.field == "storage.shares" and "obra" in str(exc.value)
    with pytest.raises(ConfigError) as exc:
        _normalize(tmp_path, {"allowed_folders": [base]})                            # las carpetas personales
    assert exc.value.field == "storage.home_template"
    # En una ubicación no es el disco del servidor: no se mira
    _normalize(tmp_path, {"allowed_folders": [base], "home_location": "nas",
                          "home_template": "homes/{username}",
                          "locations": [{"name": "nas", "type": "smb", "server": "nas", "share": "x"}],
                          "shares": [{"name": "obra", "location": "nas", "path": "/obra"}]})
    with pytest.raises(ConfigError):
        _normalize(tmp_path, {"allowed_folders": ["/tmp\x00x"]})


def test_a_folder_already_outside_does_not_open(make_app, tmp_path, home):
    (tmp_path / "fuera").mkdir()
    app = make_app({"storage": {"shares": [{"name": "vieja", "path": str(tmp_path / "fuera"), "users": ["*"]}]}})
    add_user(app, "ana")
    with app.app_context():
        get_db().execute("UPDATE users SET home_path = ? WHERE username = 'ana'", (str(tmp_path / "fuera"),))
        get_db().commit()
        ana = users.get_by_username(get_db(), "ana")
        cfg = settings()
        cfg = {**cfg, "storage": {**cfg["storage"], "allowed_folders": [str(tmp_path / "data")],
                                  "shares": []}}
        root = storage.available_roots(ana, cfg)[0]
        assert isinstance(root["backend"], UnavailableBackend)
        assert "permitidas" in root["backend"].message
        listed = storage.disk_folders(get_db(), settings(), [str(tmp_path / "data")])
    by_kind = {(f["kind"], f["label"]): f for f in listed}
    assert by_kind[("home", "Carpetas personales")]["base"] == str(tmp_path / "data")
    assert by_kind[("user", "ana")]["base"] is None and by_kind[("share", "vieja")]["base"] is None


def test_the_picker_lists_only_inside(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "uno").mkdir(parents=True)
    (b / "dos").mkdir(parents=True)
    (tmp_path / "otra").mkdir()
    both = [str(a), str(b)]
    top = pathpicker.browse_disk("", allowed=both)                     # el principio: ellas
    assert top["top"] and [e["path"] for e in top["entries"]] == both and top["error"] == ""
    inside = pathpicker.browse_disk(str(a), allowed=both)
    assert [e["name"] for e in inside["entries"]] == ["uno"] and inside["parent"] == ""   # arriba, el principio
    assert pathpicker.browse_disk(str(a / "uno"), allowed=both)["parent"] == str(a)
    out = pathpicker.browse_disk(str(tmp_path / "otra"), allowed=both)
    assert out["top"] and "permitidas" in out["error"]
    assert pathpicker.browse_disk(str(tmp_path), allowed=both)["top"]          # tampoco subiendo
    # El punto de partida (la base de las carpetas personales) fuera: en silencio, la única que hay
    one = pathpicker.browse_disk("", start=str(tmp_path / "otra"), allowed=[str(a)])
    assert one["path"] == str(a) and one["parent"] is None and one["error"] == ""


def test_the_page_and_the_route(make_app, tmp_path):
    app = make_app()
    client, _ = signed_in(app, "jefa", role="admin", csrf_url=None)
    data = settings_form(client, "server_folders")
    # Lo que queda fuera se ve antes de guardar, y no deja guardar una lista que deja fuera las personales
    page = visible(client.get("/admin/settings/server_folders").get_data(as_text=True))
    assert "Carpetas personales" in page and "sin restricción" in page
    data["allowed_folders"] = [str(tmp_path / "otra")]
    response = client.post("/admin/settings/server_folders", data=data)
    assert response.status_code == 400 and "fuera de las carpetas del servidor permitidas" in \
        response.get_data(as_text=True)
    data["allowed_folders"] = [f"{tmp_path / 'data'}\n{tmp_path / 'datos'}"]
    assert client.post("/admin/settings/server_folders", data=data).status_code == 302
    with app.app_context():
        assert settings()["storage"]["allowed_folders"] == [str(tmp_path / "data"), str(tmp_path / "datos")]
    assert "dentro de" in visible(client.get("/admin/settings/server_folders").get_data(as_text=True))
    # Una carpeta compartida nueva fuera
    (tmp_path / "fuera").mkdir()
    form = page_form(client, "/admin/access/folders/new")
    form.update({"name": ["obra"], "label": ["Obra"], "path": [str(tmp_path / "fuera")], "add_kind": ["all"],
                 "add_ref": [""], "add_level": ["write"]})
    response = client.post("/admin/access/folders/new", data=form)
    assert response.status_code == 400 and "permitidas" in response.get_data(as_text=True)
    form["path"] = [str(tmp_path / "datos" / "obra")]
    assert client.post("/admin/access/folders/new", data=form).status_code == 302
    # Una carpeta personal propia fuera
    add_user(app, "ana")
    with app.app_context():
        ana = users.get_by_username(get_db(), "ana")
        with pytest.raises(accounts.AccountError):
            accounts.update_account(get_db(), ana, ana, role="user", enabled=True, display_name=None, email=None,
                                    home_path=str(tmp_path / "fuera"), cfg=settings())
    page = client.post(f"/admin/users/{U(ana)}", data={"_csrf": data["_csrf"][0], "role": "user",
                                                        "home_path": str(tmp_path / "fuera")},
                       follow_redirects=True).get_data(as_text=True)
    assert "permitidas" in page
    with app.app_context():
        assert users.get_by_username(get_db(), "ana")["home_path"] is None
    # El selector, con la lista
    h = {"X-CSRF-Token": data["_csrf"][0]}
    got = client.get(f"/admin/browse?scope=location&path={tmp_path / 'fuera'}", headers=h).get_json()
    assert got["top"] and got["error"]


def test_locked_from_config_json(write_config, tmp_path):
    from storageweb import create_app
    path = write_config({"storage": {"allowed_folders": [str(tmp_path / "data")]}})
    app = create_app(str(path))
    client, _ = signed_in(app, "jefa", role="admin", csrf_url=None)
    html = client.get("/admin/settings/server_folders").get_data(as_text=True)
    assert 'name="allowed_folders" rows="5" class="mono" spellcheck="false"' not in html or "disabled" in html
    data = settings_form(client, "server_folders")
    assert "allowed_folders" not in data                                      # bloqueado: el navegador no lo envía
    assert json.loads(path.read_text(encoding="utf-8"))["storage"]["allowed_folders"]


def test_the_audit_file(tmp_path):
    """``audit.file``: el servidor añade líneas a ese fichero. Nunca en la carpeta de datos ni el config.json; con
    carpetas permitidas, dentro de ellas; una ruta de red, solo si está en ellas."""
    def norm(file, allowed=()):
        return normalize({"data_dir": "data", "audit": {"file": file},
                          "storage": {"home_template": str(tmp_path / "homes" / "{username}"),
                                      "allowed_folders": list(allowed)}}, tmp_path / "config.json")
    assert norm(str(tmp_path / "logs" / "audit.jsonl"))["audit"]["file"] == str(tmp_path / "logs" / "audit.jsonl")
    for bad in (str(tmp_path / "data" / "storageweb.db"), str(tmp_path / "data" / "secrets.key"),
                str(tmp_path / "data" / "x" / ".." / "storageweb.db-wal"), str(tmp_path / "config.json"),
                r"\\equipo\recurso\audit.jsonl", "//equipo/recurso/audit.jsonl"):
        with pytest.raises(ConfigError) as exc:
            norm(bad)
        assert exc.value.field == "audit.file", bad
    allowed = [str(tmp_path / "homes"), str(tmp_path / "logs")]
    norm(str(tmp_path / "logs" / "audit.jsonl"), allowed)
    with pytest.raises(ConfigError) as exc:
        norm(str(tmp_path / "otra" / "audit.jsonl"), allowed)
    assert exc.value.field == "audit.file" and "permitidas" in str(exc.value)
    norm(r"\\nas\logs\audit.jsonl", allowed + [r"\\nas\logs"])               # en una permitida, sí


def test_network_paths_only_inside_an_allowed_folder(tmp_path):
    r"""Una carpeta compartida o personal en ``\\equipo\recurso`` (sin ubicación) haría que el servidor se conectara
    a ese equipo con su cuenta: solo dentro de una carpeta permitida, aunque no haya lista."""
    unc = r"\\nas\datos\obra"
    for path in (unc, "//nas/datos/obra"):
        with pytest.raises(ConfigError) as exc:
            _normalize(tmp_path, {"shares": [{"name": "obra", "path": path}]})
        assert exc.value.field == "storage.shares" and "ruta de red" in str(exc.value) and "SMB" in str(exc.value)
    with pytest.raises(ConfigError) as exc:
        normalize({"storage": {"home_template": r"\\nas\homes\{username}"}}, tmp_path / "config.json")
    assert exc.value.field == "storage.home_template"
    _normalize(tmp_path, {"allowed_folders": [str(tmp_path / "homes"), r"\\nas\datos"],
                          "shares": [{"name": "obra", "path": unc}]})                 # dentro de una permitida
    # La carpeta personal propia y una que ya estaba (al abrirla)
    cfg = {"storage": {"home_location": "", "allowed_folders": []}}
    with pytest.raises(accounts.AccountError, match="ruta de red"):
        accounts.check_home_path(cfg, r"\\nas\homes\ana")
    accounts.check_home_path({"storage": {"home_location": "", "allowed_folders": [r"\\nas\homes"]}},
                             r"\\nas\homes\ana")
    root = storage.make_root({"storage": {"allowed_folders": [], "locations": []}, "data_dir": str(tmp_path)},
                             "obra", "Obra", "", unc)
    assert isinstance(root["backend"], UnavailableBackend) and "ruta de red" in root["backend"].message

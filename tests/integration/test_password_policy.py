"""Seguridad → Contraseñas: las reglas (longitud, tipos de caracteres, caracteres distintos, nombre de usuario,
palabras prohibidas), la lista propia de contraseñas comunes (subir, descargar, volver a la de serie; web y CLI) y la
consulta de filtraciones (Have I Been Pwned con k-anonimato)."""
from __future__ import annotations

import hashlib
import io

import pytest

from storageweb.core import passwords
from storageweb.providers import local
from storageweb.providers.local import breach
from storageweb.settings import ConfigError
from storageweb.settings.loader import normalize
from storageweb.web.context import boot_config
from tests.helpers import PASSWORD, get_csrf, run_cli, settings_form, stored_settings, visible, signed_in


def test_the_rules():
    ok = "caballo-grapa-bateria"
    local.validate_password(ok, require=("lower", "symbol"))
    with pytest.raises(ValueError, match="una mayúscula, un número"):
        local.validate_password(ok, require=("upper", "digit", "lower"))
    local.validate_password("Caballo-Grapa-7", require=("lower", "upper", "digit", "symbol"))
    local.validate_password("abcabcabcabc", min_distinct=3, check_common=False)
    with pytest.raises(ValueError, match="muy pocos"):
        local.validate_password("abcabcabcabc", min_distinct=4)
    # El nombre de usuario: contenerlo (desde 4 caracteres), y se puede apagar
    with pytest.raises(ValueError, match="nombre de usuario"):
        local.validate_password("mi-clave-de-AnaBelen", username="anabelen")
    local.validate_password("mi-clave-de-anabelen", username="anabelen", reject_username=False)
    local.validate_password("una-clave-con-ana-dentro", username="ana")          # 3 letras: solo si es igual
    # Palabras prohibidas: contenerlas, sin distinguir mayúsculas; aunque las comunes estén apagadas
    with pytest.raises(ValueError, match="«contoso»"):
        local.validate_password("Contoso-2026-ok", blocklist=("contoso",), check_common=False)
    # Lo que se pide, en una frase
    assert local.describe({"min_length": 12, "require": ("upper", "digit")}) == \
        "Al menos 12 caracteres, con una mayúscula, un número."
    assert local.describe({"min_length": 4}) == "Al menos 10 caracteres."


def test_breach_check_sends_only_a_prefix(monkeypatch):
    password = "caballo-grapa-bateria"
    digest = hashlib.sha1(password.encode()).hexdigest().upper()
    asked = []

    def fake(prefix, timeout):
        asked.append(prefix)
        return f"0000000000000000000000000000000000A:3\r\n{digest[5:]}:42\r\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:0"
    monkeypatch.setattr(breach, "_fetch", fake)
    with pytest.raises(ValueError, match="42 filtraciones"):
        local.validate_password(password, breach_check=True)
    assert asked == [digest[:5]]                                                 # solo los 5 primeros
    local.validate_password(password, breach_check=False)                       # apagado: no pregunta
    assert len(asked) == 1
    monkeypatch.setattr(breach, "_fetch", lambda prefix, timeout: "ABC:1")
    local.validate_password(password, breach_check=True)                        # no está
    def down(prefix, timeout):
        raise OSError("sin red")
    monkeypatch.setattr(breach, "_fetch", down)
    local.validate_password(password, breach_check=True)                        # sin servicio: se acepta


def test_settings_are_validated(tmp_path):
    def norm(sec):
        return normalize({"security": sec}, tmp_path / "config.json")
    got = norm({"password_require": ["digit", "upper"], "password_blocklist": "Contoso\ncontoso\n madrid ",
                "password_list_urls": "https://ejemplo.es/a.txt\n"})["security"]
    assert got["password_require"] == ["upper", "digit"] and got["password_blocklist"] == ["contoso", "madrid"]
    assert got["password_list_urls"] == ["https://ejemplo.es/a.txt"]
    for sec, field in (({"password_require": ["emoji"]}, "security.password_require"),
                       ({"password_blocklist": ["abc"]}, "security.password_blocklist"),
                       ({"password_list_urls": ["http://ejemplo.es/a.txt"]}, "security.password_list_urls"),
                       ({"password_min_distinct": 0}, "security.password_min_distinct")):
        with pytest.raises(ConfigError) as exc:
            norm(sec)
        assert exc.value.field == field


def test_own_list(tmp_path):
    assert not passwords.status(tmp_path)["own"]
    with pytest.raises(passwords.PasswordListError):
        passwords.install(tmp_path, ["corta\notra\n"], "prueba")                  # nada de 10 o más
    count = passwords.install(tmp_path, ["# comentario\nNuestraClave2026\nnuestraclave2026\ncorta\n"], "prueba")
    state = passwords.status(tmp_path)
    assert count == 1 and state["own"] and state["count"] == 1 and state["source"] == "prueba" and state["updated_at"]
    rules = local.rules({"security": {}, "data_dir": str(tmp_path)})
    with pytest.raises(ValueError, match="más comunes"):
        local.validate_password("NuestraClave2026", **rules)
    local.validate_password("password1234", **rules)                    # la de serie ya no se usa
    passwords.install(tmp_path, ["otra-clave-nueva\n"], "prueba")       # cambia el fichero: se vuelve a leer
    local.validate_password("NuestraClave2026", **rules)
    assert passwords.reset(tmp_path) and not passwords.reset(tmp_path)
    with pytest.raises(ValueError, match="más comunes"):
        local.validate_password("password1234", **local.rules({"security": {}, "data_dir": str(tmp_path)}))


def test_download(tmp_path, monkeypatch):
    with pytest.raises(passwords.PasswordListError, match="https"):
        passwords.download(tmp_path, ["http://ejemplo.es/lista.txt"])
    got = {"https://a/1.txt": b"primera-clave-1\n", "https://a/2.txt": "segunda-contraseña\n".encode()}
    monkeypatch.setattr(passwords, "_download", lambda url, budget: got[url])
    assert passwords.download(tmp_path, list(got)) == 2
    assert passwords.status(tmp_path)["source"] == "https://a/1.txt https://a/2.txt"
    monkeypatch.setattr(passwords, "MAX_BYTES", 10)
    with pytest.raises(passwords.PasswordListError, match="MB"):
        passwords.upload(tmp_path, b"x" * 11, "grande.txt")


def test_the_page(app, admin, monkeypatch):
    client, token = admin
    page = visible(client.get("/admin/settings/passwords").get_data(as_text=True))
    assert "La lista que viene con StorageWeb" in page and "Volver a la de serie" not in page
    assert 'name="password_check"' not in client.get("/admin/settings/auth").get_data(as_text=True)
    data = settings_form(client, "passwords")
    data.update({"password_require": ["upper", "digit"], "password_blocklist": ["Contoso"],
                 "password_min_distinct": ["6"], "password_breach_check": ["on"]})
    assert client.post("/admin/settings/passwords", data=data).status_code == 302
    sec = stored_settings(app)["security"]
    assert sec["password_require"] == ["upper", "digit"] and sec["password_blocklist"] == ["contoso"]
    assert sec["password_min_distinct"] == 6 and sec["password_breach_check"] is True
    # Lo que se pide se dice al poner una contraseña
    monkeypatch.setattr(breach, "_fetch", lambda prefix, timeout: "")
    ana, _ = signed_in(app, "ana", csrf_url=None)
    assert "con una mayúscula, un número" in ana.get("/profile/security").get_data(as_text=True)
    t = get_csrf(ana, "/profile/security")
    page = ana.post("/profile/password", data={"_csrf": t, "current_password": PASSWORD,
                                               "new_password": "Contoso-clave-9", "repeat_password": "Contoso-clave-9"},
                    follow_redirects=True).get_data(as_text=True)
    assert "«contoso»" in page
    # Subir una lista, y volver a la de serie
    response = client.post("/admin/settings/passwords/list/upload", content_type="multipart/form-data",
                           data={"_csrf": token, "file": (io.BytesIO(b"Mi-Clave-De-Empresa1\n"), "lista.txt")},
                           follow_redirects=True)
    assert "1 contraseñas" in response.get_data(as_text=True)
    with app.app_context():
        assert passwords.status(boot_config()["data_dir"])["own"]
    assert "Volver a la de serie" in client.get("/admin/settings/passwords").get_data(as_text=True)
    t = get_csrf(ana, "/profile/security")
    page = ana.post("/profile/password", data={"_csrf": t, "current_password": PASSWORD,
                                               "new_password": "Mi-Clave-De-Empresa1",
                                               "repeat_password": "Mi-Clave-De-Empresa1"},
                    follow_redirects=True).get_data(as_text=True)
    assert "más comunes" in page
    client.post("/admin/settings/passwords/list/reset", data={"_csrf": token})
    with app.app_context():
        assert not passwords.status(boot_config()["data_dir"])["own"]
    # Descargar: de las direcciones guardadas
    monkeypatch.setattr(passwords, "_download", lambda url, budget: b"descargada-clave-1\n")
    response = client.post("/admin/settings/passwords/list/download", data={"_csrf": token}, follow_redirects=True)
    assert "1 contraseñas" in response.get_data(as_text=True)


def test_the_cli(write_config, tmp_path):
    cfg = write_config()
    lista = tmp_path / "lista.txt"
    lista.write_text("clave-de-la-casa-1\n", encoding="utf-8")

    def run(*args):
        return run_cli(cfg, *args, ok=True).stdout
    assert "La lista que viene con StorageWeb" in run("password-list")
    assert "1 contraseñas" in run("password-list", "--file", str(lista))
    assert "Lista propia" in run("password-list")
    assert "Se vuelve a usar" in run("password-list", "--reset")


def test_the_tester(app, admin, monkeypatch):
    client, token = admin
    h = {"X-CSRF-Token": token}
    got = client.post("/admin/settings/passwords/test", data={"test_password": "qwertyuiop", "test_username": "ana"},
                      headers=h).get_json()
    by_key = {c["key"]: c for c in got["checks"]}
    assert not got["ok"] and "Se rechazaría: no cumple 1 regla" in got["summary"]
    assert by_key["length"]["ok"] and by_key["username"]["ok"] and by_key["common"]["ok"] is False
    assert "breach" not in by_key                                              # apagado: ni se muestra
    got = client.post("/admin/settings/passwords/test", data={"test_password": "caballo-grapa-bateria"}, headers=h)
    assert got.get_json()["ok"] and got.get_json()["summary"] == "Se aceptaría."
    # Con las filtraciones: sin servicio, «sin comprobar», y no cuenta como fallo
    from tests.helpers import update_settings
    update_settings(app, security={"password_breach_check": True, "password_require": ["upper"]})
    def down(prefix, timeout):
        raise OSError("sin red")
    monkeypatch.setattr(breach, "_fetch", down)
    got = client.post("/admin/settings/passwords/test", data={"test_password": "Caballo-grapa-bateria"},
                      headers=h).get_json()
    by_key = {c["key"]: c for c in got["checks"]}
    assert got["ok"] and by_key["breach"]["ok"] is None and "no ha contestado" in by_key["breach"]["message"]
    assert by_key["require"]["label"] == "Con una mayúscula"
    # Solo administradores, y solo desde la página (CSRF)
    assert client.post("/admin/settings/passwords/test", data={"test_password": "x"}).status_code in (400, 403)
    luis, _ = signed_in(app, "luis", csrf_url=None)
    assert luis.post("/admin/settings/passwords/test", data={"test_password": "x"},
                     headers={"X-CSRF-Token": get_csrf(luis, "/profile/security")}).status_code == 403



def test_the_tester_uses_the_page(app, admin, monkeypatch):
    """Con el formulario de la página (``from_page=1``), sus reglas aunque no estén guardadas; mal escritas, el error
    de la validación; nunca guarda nada."""
    client, token = admin
    h = {"X-CSRF-Token": token}
    monkeypatch.setattr(breach, "_fetch", lambda prefix, timeout: "")
    page = settings_form(client, "passwords")
    page.update({"password_breach_check": ["on"], "password_require": ["upper"], "from_page": ["1"],
                 "test_password": ["caballo-grapa-bateria"]})
    got = client.post("/admin/settings/passwords/test", data=page, headers=h).get_json()
    keys = [c["key"] for c in got["checks"]]
    assert "breach" in keys and "require" in keys and not got["ok"]
    assert stored_settings(app)["security"].get("password_breach_check") is not True     # no se ha guardado
    page["password_blocklist"] = ["abc"]                                                 # demasiado corta
    got = client.post("/admin/settings/passwords/test", data=page, headers=h).get_json()
    assert not got["ok"] and "demasiado corta" in got["summary"]

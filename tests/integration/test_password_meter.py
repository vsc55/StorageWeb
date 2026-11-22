"""El medidor de contraseñas nuevas (Mi perfil y el modal de Cambiar contraseña de otra cuenta): fortaleza, las reglas
del sistema mientras se escribe y el generador que las cumple."""
from __future__ import annotations

from storageweb.providers import local
from tests.helpers import U, add_user, signed_in, update_settings

CHECK, GENERATE = "/profile/password/check", "/profile/password/generate"


def _post(client, csrf, url, **data):
    return client.post(url, data=data, headers={"X-CSRF-Token": csrf, "Accept": "application/json"})


def test_strength_scale():
    assert local.strength("") == local.strength("aaaaaaaaaaaa") == 0
    assert local.strength("password1234") <= 1
    assert local.strength("abcdefghijkl") < local.strength("Tr4n-qu1L0!casa") <= local.strength("B7qcYG2zrF~7XM!wn6SA")
    assert local.strength("B7qcYG2zrF~7XM!wn6SA") == 4


def test_generated_passwords_follow_the_rules():
    rules = {"min_length": 24, "require": ("upper", "digit", "symbol"), "blocklist": ("ana",), "check_common": True}
    seen = set()
    for _ in range(20):
        password = local.generate(username="ana", **rules)
        assert len(password) >= 24 and password not in seen
        assert all(c["ok"] is not False for c in local.checks(password, username="ana", **rules))
        assert not set(password) & set("lIO01")                      # sin los que se confunden
        seen.add(password)


def test_check_says_each_rule_and_the_strength(app):
    update_settings(app, security={"password_require": ["upper", "digit"], "password_blocklist": ["empresa"],
                                   "password_breach_check": True})
    client, csrf = signed_in(app)
    weak = _post(client, csrf, CHECK, password="empresa-ana").get_json()
    assert not weak["ok"] and weak["score"] <= 1 and weak["label"] in ("Muy débil", "Débil")
    bad = {c["key"] for c in weak["checks"] if c["ok"] is False}
    assert {"require", "blocklist"} <= bad                                # («ana»: menos de 4 letras, solo si es igual)
    breach = next(c for c in weak["checks"] if c["key"] == "breach")      # va a internet: al guardar
    assert breach["ok"] is None and "al guardar" in breach["message"]
    good = _post(client, csrf, CHECK, password="Tr4n-qu1L0!casa-9").get_json()
    assert good["ok"] and good["score"] >= 3


def test_an_admin_checks_with_the_rules_of_the_other_account(app):
    client, csrf = signed_in(app, "root", role="admin")
    luis = add_user(app, "luis")
    mine = _post(client, csrf, CHECK, password="luis-Clave-2026!")
    theirs = _post(client, csrf, CHECK, password="luis-Clave-2026!", user=U(luis))
    assert mine.get_json()["ok"] and not theirs.get_json()["ok"]          # contiene SU nombre de usuario
    other, csrf2 = signed_in(app, "ana")
    assert _post(other, csrf2, CHECK, password="x", user=U(luis)).status_code == 403   # solo un admin


def test_generate_and_it_needs_a_session(app):
    update_settings(app, security={"password_min_length": 30, "password_require": ["symbol"]})
    client, csrf = signed_in(app)
    password = _post(client, csrf, GENERATE).get_json()["password"]
    assert len(password) >= 30 and _post(client, csrf, CHECK, password=password).get_json()["ok"]
    stranger = app.test_client()
    assert stranger.post(CHECK, data={"password": "x"}, headers={"Accept": "application/json"}).status_code in (400, 401)


def test_the_pages_have_the_meter(app):
    client, _csrf = signed_in(app, "root", role="admin")
    luis = add_user(app, "luis")
    page = client.get("/profile/security").get_data(as_text=True)
    assert 'class="span2 pw-meter"' in page and "password-meter.js" in page and "js-pw-generate" in page
    modal = client.get(f"/admin/users/{U(luis)}/password?modal=1").get_data(as_text=True)
    assert f'data-user="{U(luis)}"' in modal
    assert "password-meter.js" in client.get("/admin/users").get_data(as_text=True)


def test_new_user_form_has_the_meter_and_checks_the_repeat(app):
    from storageweb.db.repositories import users
    from storageweb.web.context import get_db
    client, csrf = signed_in(app, "root", role="admin")
    page = client.get("/admin/users/new").get_data(as_text=True)
    assert 'data-username-from="input[name=username]"' in page and "password-meter.js" in page
    # Para una cuenta que aún no existe, las reglas con el nombre que se escribe (solo un admin)
    assert not _post(client, csrf, CHECK, password="mariano-Clave-26!", username="mariano").get_json()["ok"]
    other, csrf2 = signed_in(app, "ana")
    assert _post(other, csrf2, CHECK, password="x", username="mariano").status_code == 403
    form = {"_csrf": csrf, "username": "mariano", "source": "local", "role": "user", "enabled": "on",
            "password": "Tr4n-qu1L0!casa-9", "repeat_password": "otra"}
    assert "no coinciden" in client.post("/admin/users/new", data=form, follow_redirects=True).get_data(as_text=True)
    with app.app_context():
        assert users.get_by_username(get_db(), "mariano") is None
    form["repeat_password"] = form["password"]
    assert client.post("/admin/users/new", data=form).status_code == 302
    with app.app_context():
        assert users.get_by_username(get_db(), "mariano") is not None


def test_the_tester_has_the_strength_and_generates_with_the_page_rules(app):
    client, csrf = signed_in(app, "root", role="admin", csrf_url="/admin/settings/passwords")
    page = client.get("/admin/settings/passwords").get_data(as_text=True)
    assert "js-generate" in page and "pw-strength" in page and "password-meter.js" in page
    tried = client.post("/admin/settings/passwords/test", data={"test_password": "abc"},
                        headers={"X-CSRF-Token": csrf, "Accept": "application/json"}).get_json()
    assert tried["score"] == 0 and tried["label"] == "Muy débil" and not tried["ok"]
    # Con las reglas que hay en la página aunque no estén guardadas (aquí, 40 caracteres como mínimo)
    from tests.helpers import settings_form
    data = {**settings_form(client, "passwords"), "password_min_length": ["40"], "from_page": "1"}
    made = client.post("/admin/settings/passwords/generate", data=data,
                       headers={"X-CSRF-Token": csrf, "Accept": "application/json"}).get_json()
    assert len(made["password"]) >= 40


def test_the_tester_while_typing_does_not_go_to_the_internet(app, monkeypatch):
    """Mientras se escribe (live=1) no se pregunta a Have I Been Pwned en cada tecla: solo con el botón «Probar»."""
    from storageweb.providers.local import breach
    asked = []
    monkeypatch.setattr(breach, "times_breached", lambda password: asked.append(password) or 0)
    update_settings(app, security={"password_breach_check": True})
    client, csrf = signed_in(app, "root", role="admin", csrf_url="/admin/settings/passwords")
    headers = {"X-CSRF-Token": csrf, "Accept": "application/json"}
    live = client.post("/admin/settings/passwords/test", data={"test_password": "Tr4n-qu1L0!casa", "live": "1"},
                       headers=headers).get_json()
    found = next(c for c in live["checks"] if c["key"] == "breach")
    assert asked == [] and found["ok"] is None and "Probar" in found["message"]
    pressed = client.post("/admin/settings/passwords/test", data={"test_password": "Tr4n-qu1L0!casa"},
                          headers=headers).get_json()
    assert asked == ["Tr4n-qu1L0!casa"] and next(c for c in pressed["checks"] if c["key"] == "breach")["ok"] is True

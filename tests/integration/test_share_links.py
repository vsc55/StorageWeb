"""Enlaces para compartir (core/links.py, web/views/links.py): crearlos, abrirlos sin cuenta, contraseña, caducidad,
límite de descargas, buzones, que nunca salgan de lo compartido, que sigan al archivo y quién los quita."""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone

import pytest

from storageweb.core import links
from storageweb.db.repositories import share_links as repo
from storageweb.db.repositories import users
from storageweb.web.context import get_db
from tests.helpers import get_csrf, login, update_settings, visible, signed_in


def _share(client, token, path, **form):
    resp = client.post("/links", data={"root": "home", "path": path, **form},
                       headers={"X-CSRF-Token": token, "Accept": "application/json"})
    return resp.status_code, resp.get_json()


def _token(url: str) -> str:
    return url.rsplit("/s/", 1)[1]


ALL = {p: True for p in ("upload", "download", "mkdir", "rename", "delete", "share")}


@pytest.fixture
def sharer(app, logged, home):
    """Ana, con permiso para compartir y unos archivos."""
    update_settings(app, permissions={"user": ALL})
    (home / "Docs" / "sub").mkdir(parents=True)
    (home / "Docs" / "plan.txt").write_text("el plan", encoding="utf-8")
    (home / "Docs" / "sub" / "dentro.txt").write_text("dentro", encoding="utf-8")
    (home / "Docs" / "secreto.tmp").write_text("no", encoding="utf-8")
    (home / "fuera.txt").write_text("fuera", encoding="utf-8")
    return logged


def test_share_a_file_without_an_account(app, sharer):
    client, token = sharer
    code, data = _share(client, token, "Docs/plan.txt")
    assert code == 200 and "/s/" in data["url"]
    anon = app.test_client()
    t = _token(data["url"])
    page = anon.get(f"/s/{t}")
    assert page.status_code == 200 and "plan.txt" in page.get_data(as_text=True)
    assert "Ana López" in page.get_data(as_text=True)                     # quién lo comparte
    assert page.headers["Referrer-Policy"] == "no-referrer" and "noindex" in page.headers["X-Robots-Tag"]
    got = anon.get(f"/s/{t}/download")
    assert got.status_code == 200 and got.data == b"el plan" and "attachment" in got.headers["Content-Disposition"]
    assert anon.get(f"/s/{t}/download?p=../fuera.txt").status_code == 404   # un enlace a un archivo: solo ese
    # Ni el token en claro en la base de datos
    with app.app_context():
        row = links.find(get_db(), t)
        assert row["token_hash"] != t and t not in row["token_enc"] and row["token_enc"].startswith("enc:")
        assert row["downloads"] == 1
        actions = [r["action"] for r in get_db().execute("SELECT action FROM audit_log")]
    assert "link_created" in actions and "link_download" in actions


def test_a_folder_never_leaves_what_was_shared(app, sharer):
    client, token = sharer
    update_settings(app, storage={"hidden": ["*.tmp"]})
    code, data = _share(client, token, "Docs")
    t = _token(data["url"])
    anon = app.test_client()
    page = visible(anon.get(f"/s/{t}").get_data(as_text=True))
    assert "plan.txt" in page and "sub" in page and "secreto.tmp" not in page   # lo oculto para todos, oculto
    assert "dentro.txt" in anon.get(f"/s/{t}?p=sub").get_data(as_text=True)
    assert anon.get(f"/s/{t}/download?p=sub/dentro.txt").data == b"dentro"
    for bad in ("../fuera.txt", "sub/../../fuera.txt", "/etc/passwd", "..", "secreto.tmp"):
        assert anon.get(f"/s/{t}/download", query_string={"p": bad}).status_code == 404, bad
        assert anon.get(f"/s/{t}", query_string={"p": bad}).status_code == 404, bad
    zipped = anon.get(f"/s/{t}/zip")
    assert zipped.status_code == 200 and zipped.mimetype == "application/zip"
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(zipped.data)).namelist()
    assert any(n.endswith("plan.txt") for n in names) and not any("fuera" in n or n.endswith(".tmp") for n in names)


def test_password_expiry_and_download_limit(app, sharer):
    client, token = sharer
    code, data = _share(client, token, "Docs/plan.txt", password="corta")
    assert code == 400 and "8" in data["error"]
    code, data = _share(client, token, "Docs/plan.txt", password="una-clave-larga", max_downloads="2")
    t = _token(data["url"])
    anon = app.test_client()
    assert "contraseña" in anon.get(f"/s/{t}").get_data(as_text=True)
    assert anon.get(f"/s/{t}/download").status_code == 404                   # sin la contraseña, nada
    csrf = get_csrf(anon, f"/s/{t}")
    page = anon.post(f"/s/{t}", data={"_csrf": csrf, "password": "mal"}, follow_redirects=True)
    assert "Contraseña incorrecta" in page.get_data(as_text=True)
    anon.post(f"/s/{t}", data={"_csrf": csrf, "password": "una-clave-larga"})
    assert anon.get(f"/s/{t}/download").status_code == 200
    assert anon.get(f"/s/{t}/download").status_code == 200
    assert anon.get(f"/s/{t}/download").status_code == 410                   # 2 descargas y ya
    assert anon.get(f"/s/{t}").status_code == 410
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM audit_log WHERE action = 'link_password_failed'").fetchone()[0] == 1
    # Caducado
    code, data = _share(client, token, "Docs/plan.txt", days="1")
    t2 = _token(data["url"])
    with app.app_context():
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        get_db().execute("UPDATE share_links SET expires_at = ? WHERE id = ?", (past, links.find(get_db(), t2)["id"]))
        get_db().commit()
    assert app.test_client().get(f"/s/{t2}").status_code == 410
    assert app.test_client().get("/s/no-existe-este-token").status_code == 404


def test_the_rules_of_the_settings(app, sharer):
    client, token = sharer
    update_settings(app, sharing={"max_days": 7, "default_days": 7})
    code, data = _share(client, token, "Docs/plan.txt", days="30")
    assert code == 400 and "7" in data["error"]
    code, data = _share(client, token, "Docs/plan.txt", days="0")            # sin caducidad: no, con máximo
    assert code == 400
    update_settings(app, sharing={"require_password": True})
    assert _share(client, token, "Docs/plan.txt")[0] == 400
    assert _share(client, token, "Docs/plan.txt", password="una-clave-larga")[0] == 200
    update_settings(app, sharing={"links": False})
    assert _share(client, token, "Docs/plan.txt", password="una-clave-larga")[0] == 400
    # Sin el permiso del rol
    update_settings(app, sharing={"links": True, "require_password": False},
                    permissions={"user": {**ALL, "share": False}})
    code, data = _share(client, token, "Docs/plan.txt")
    assert code == 400 and "No puedes compartir" in data["error"]
    assert 'data-action="share"' not in client.get("/f/home/").get_data(as_text=True)


def test_drop_box(app, sharer, home):
    client, token = sharer
    assert _share(client, token, "Docs/plan.txt", mode="upload")[0] == 400   # un buzón es para carpetas
    code, data = _share(client, token, "Docs", mode="upload")
    t = _token(data["url"])
    anon = app.test_client()
    page = anon.get(f"/s/{t}").get_data(as_text=True)
    assert 'type="file"' in page and "plan.txt" not in page                  # no se ve lo que hay
    assert anon.get(f"/s/{t}/download?p=plan.txt").status_code == 404
    assert anon.get(f"/s/{t}/zip").status_code == 404
    csrf = get_csrf(anon, f"/s/{t}")
    anon.post(f"/s/{t}/upload", data={"_csrf": csrf, "files": [(io.BytesIO(b"nuevo"), "plan.txt"),
                                                               (io.BytesIO(b"otro"), "../escapa.txt")]},
              content_type="multipart/form-data")
    assert (home / "Docs" / "plan.txt").read_text(encoding="utf-8") == "el plan"     # nunca sobrescribe
    assert (home / "Docs" / "plan (1).txt").read_bytes() == b"nuevo"
    assert not (home / "escapa.txt").exists()
    update_settings(app, sharing={"upload_links": False})
    assert _share(client, token, "Docs", mode="upload")[0] == 400


def test_the_link_follows_the_owner_and_the_file(app, sharer, home):
    client, token = sharer
    t = _token(_share(client, token, "Docs/plan.txt")[1]["url"])
    anon = app.test_client()
    client.post("/rename/home/Docs/plan.txt", data={"_csrf": token, "name": "plan-v2.txt"})
    page = anon.get(f"/s/{t}").get_data(as_text=True)
    assert "plan-v2.txt" in page                                            # sigue al archivo
    update_settings(app, permissions={"user": {**ALL, "share": False}})
    assert anon.get(f"/s/{t}").status_code == 404                           # quien lo creó ya no puede compartir
    update_settings(app, permissions={"user": ALL})
    with app.app_context():
        get_db().execute("UPDATE users SET enabled = 0 WHERE username = 'ana'")
        get_db().commit()
    assert anon.get(f"/s/{t}").status_code == 404                           # ni con su cuenta desactivada
    with app.app_context():
        get_db().execute("UPDATE users SET enabled = 1 WHERE username = 'ana'")
        get_db().commit()
    again = app.test_client()                                                # la sesión se cerró al desactivarla
    assert login(again, "ana").status_code == 302
    again.post("/delete/home/Docs", data={"_csrf": get_csrf(again, "/f/home/")})
    with app.app_context():
        gone = repo.list_all(get_db())
        assert [links.state(r) for r in gone] == ["revoked"] and gone[0]["revoke_reason"] == "deleted"   # quitado


def test_who_removes_them(app, sharer):
    client, token = sharer
    data = _share(client, token, "Docs/plan.txt")[1]
    t = _token(data["url"])
    page = client.get("/profile/links").get_data(as_text=True)
    assert data["url"] in page and "Dejar de compartir" in page               # su dueño lo vuelve a copiar
    luis, _ = signed_in(app, "luis", csrf_url=None)
    assert luis.post(f"/links/{data['uid']}/revoke", data={"_csrf": get_csrf(luis, "/f/home/")}).status_code == 404
    root, _ = signed_in(app, "root", role="admin", csrf_url=None)
    admin_page = root.get("/admin/settings/sharing").get_data(as_text=True)
    assert "ana" in admin_page and data["url"] not in admin_page              # la lista, sin las direcciones
    root.post(f"/links/{data['uid']}/revoke", data={"_csrf": get_csrf(root, "/admin/settings/sharing")})
    assert app.test_client().get(f"/s/{t}").status_code == 410                # quitado (no borrado)


def test_purge_of_old_expired(app, sharer):
    client, token = sharer
    t = _token(_share(client, token, "Docs/plan.txt")[1]["url"])
    with app.app_context():
        long_ago = (datetime.now(timezone.utc) - timedelta(days=links.KEEP_EXPIRED_DAYS + 1)).isoformat()
        get_db().execute("UPDATE share_links SET expires_at = ?", (long_ago,))
        get_db().commit()
        links._purge(get_db(), {})  # noqa: SLF001
        assert links.find(get_db(), t) is None



def test_activity_is_kept_for_traceability(app, sharer, home):
    """Cada visita, descarga, contraseña equivocada o intento rechazado queda con su fecha, IP y navegador; quitar el
    enlace no borra nada de eso, y solo lo ven su dueño y los administradores."""
    client, token = sharer
    data = _share(client, token, "Docs", password="una-clave-larga", max_downloads="1")[1]
    t, uid = _token(data["url"]), data["uid"]
    anon = app.test_client()
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Firefox/140.0"}
    anon.get(f"/s/{t}", headers=ua)                                                  # pide la contraseña
    csrf = get_csrf(anon, f"/s/{t}")
    anon.post(f"/s/{t}", data={"_csrf": csrf, "password": "mal"}, headers=ua)
    anon.post(f"/s/{t}", data={"_csrf": csrf, "password": "una-clave-larga"}, headers=ua)
    anon.get(f"/s/{t}?p=sub", headers=ua)
    assert anon.get(f"/s/{t}/download?p=plan.txt", headers=ua).status_code == 200
    assert anon.get(f"/s/{t}/download?p=plan.txt", headers=ua).status_code == 410      # sin descargas
    with app.app_context():
        events = [(e["event"], e["path"], e["detail"]) for e in reversed(links.events(get_db(), uid))]
        ips = {e["ip"] for e in links.events(get_db(), uid) if e["event"] != "created"}
        agents = {e["user_agent"] for e in links.events(get_db(), uid) if e["event"] != "created"}
    kinds = [e[0] for e in events]
    assert kinds[:1] == ["created"] and "password_failed" in kinds and "unlocked" in kinds
    assert ("opened", "Docs/sub", None) in events and ("download", "Docs/plan.txt", "7") in events
    assert ("refused", "Docs/plan.txt", "used_up") in events or ("refused", None, "used_up") in events
    assert ips == {"127.0.0.1"} and any("Firefox" in (a or "") for a in agents)
    page = client.get(f"/links/{uid}/activity").get_data(as_text=True)
    assert "Contraseña equivocada" in page and "Docs/plan.txt" in page and "Firefox" in page
    csv = client.get(f"/links/{uid}/activity.csv")
    assert csv.mimetype == "text/csv" and "password_failed" in csv.get_data(as_text=True)
    # Quitarlo: deja de funcionar, se ve como quitado y el historial sigue
    client.post(f"/links/{uid}/revoke", data={"_csrf": token})
    assert anon.get(f"/s/{t}").status_code == 410
    page = client.get(f"/links/{uid}/activity").get_data(as_text=True)
    assert "Quitado" in page and "Contraseña equivocada" in page
    assert "Quitado" in client.get("/profile/links?show=revoked").get_data(as_text=True)
    # Otra persona no lo ve; un administrador sí
    luis, _ = signed_in(app, "luis", csrf_url=None)
    assert luis.get(f"/links/{uid}/activity").status_code == 404
    root, _ = signed_in(app, "root", role="admin", csrf_url=None)
    assert root.get(f"/links/{uid}/activity").status_code == 200
    assert "visita" in root.get("/admin/settings/sharing?show=all").get_data(as_text=True)
    # La limpieza borra el enlace viejo pero no su historial
    with app.app_context():
        long_ago = (datetime.now(timezone.utc) - timedelta(days=links.KEEP_EXPIRED_DAYS + 1)).isoformat()
        get_db().execute("UPDATE share_links SET revoked_at = ?", (long_ago,))
        get_db().commit()
        links._purge(get_db(), {"maintenance": {"audit_retention_days": 0}})  # noqa: SLF001
        assert links.get(get_db(), uid) is None and len(links.events(get_db(), uid)) >= 8


def test_filters_deleted_history_and_retention(app, sharer):
    """La lista enseña los activos y filtra el resto con su número; los que la limpieza ya borró siguen en
    «Borrados» con su actividad; los plazos se ajustan y lo que se borra queda en la auditoría."""
    client, token = sharer
    live = _share(client, token, "Docs/plan.txt")[1]
    gone = _share(client, token, "fuera.txt")[1]
    client.post(f"/links/{gone['uid']}/revoke", data={"_csrf": token})
    page = visible(client.get("/profile/links").get_data(as_text=True))
    assert "1 activo" in page and "1 quitado" in page and "2 en total" in page and "0 borrados" in page
    assert "plan.txt" in page and "fuera.txt" not in page                             # de entrada, los activos
    revoked = visible(client.get("/profile/links?show=revoked").get_data(as_text=True))
    assert "fuera.txt" in revoked and "plan.txt" not in revoked
    again = visible(client.get("/profile/links").get_data(as_text=True))           # al volver, el último filtro
    assert "fuera.txt" in again and "plan.txt" not in again
    client.get("/profile/links?show=active")
    # La limpieza respeta sharing.keep_days (0 = nunca)
    with app.app_context():
        long_ago = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        get_db().execute("UPDATE share_links SET revoked_at = ? WHERE uid = ?", (long_ago, gone["uid"]))
        get_db().commit()
        links._purge(get_db(), {"sharing": {"keep_days": 0, "history_days": 0}})  # noqa: SLF001
        assert links.get(get_db(), gone["uid"]) is not None
        links._purge(get_db(), {"sharing": {"keep_days": 30, "history_days": 0}})  # noqa: SLF001
        assert links.get(get_db(), gone["uid"]) is None and links.get(get_db(), live["uid"]) is not None
        purged = get_db().execute("SELECT detail FROM audit_log WHERE action = 'links_purged'").fetchall()
        assert [r["detail"] for r in purged] == ["links=1 events=0"]
    # Borrado: su historial sigue a la vista de su dueño y de un administrador, no de otros
    deleted = visible(client.get("/profile/links?show=deleted").get_data(as_text=True))
    assert "1 borrado" in deleted and "home:/fuera.txt" in deleted
    activity = client.get(f"/links/{gone['uid']}/activity")
    assert activity.status_code == 200 and "ya no existe" in activity.get_data(as_text=True)
    assert client.get(f"/links/{gone['uid']}/activity.csv").status_code == 200
    luis, _ = signed_in(app, "luis", csrf_url=None)
    assert luis.get(f"/links/{gone['uid']}/activity").status_code == 404
    assert "fuera.txt" not in luis.get("/profile/links?show=deleted").get_data(as_text=True)
    root, _ = signed_in(app, "root", role="admin", csrf_url=None)
    admin = visible(root.get("/admin/settings/sharing?show=deleted").get_data(as_text=True))
    assert "home:/fuera.txt" in admin and root.get(f"/links/{gone['uid']}/activity").status_code == 200
    # El historial se borra con sharing.history_days
    with app.app_context():
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        get_db().execute("UPDATE share_link_events SET at = ? WHERE link_uid = ?", (old, gone["uid"]))
        get_db().commit()
        links._purge(get_db(), {"sharing": {"keep_days": 30, "history_days": 60}})  # noqa: SLF001
        assert links.events(get_db(), gone["uid"]) == [] and links.events(get_db(), live["uid"])
    assert client.get(f"/links/{gone['uid']}/activity").status_code == 404


def test_retention_settings_are_checked(app, admin):
    client, token = admin
    resp = client.post("/admin/settings/sharing", data={"_csrf": token, "sharing_default_days": "7",
                                                         "sharing_max_days": "30", "sharing_keep_days": "30",
                                                         "sharing_history_days": "10"})
    assert "no puede ser menor" in resp.get_data(as_text=True)
    resp = client.post("/admin/settings/sharing", data={"_csrf": token, "sharing_default_days": "7",
                                                         "sharing_max_days": "30", "sharing_keep_days": "15",
                                                         "sharing_history_days": "90"}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        from storageweb.web.context import settings
        assert settings()["sharing"]["keep_days"] == 15 and settings()["sharing"]["history_days"] == 90

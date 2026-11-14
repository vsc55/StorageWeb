"""Registros que se rellenan solos: avisos, tareas de mantenimiento, comandos de la CLI y buscador.

Cada uno se prueba registrando algo desde aquí: el código general lo recoge sin cambios.
"""
import json

import pytest

from storageweb import registry
from storageweb.cli import build_parser, commands, main
from storageweb.cli import common as cli_common
from storageweb.core import alerts, maintenance
from storageweb.settings import load_config


@pytest.fixture
def cfg(tmp_path, db_conn):
    database = db_conn.execute("PRAGMA database_list").fetchone()["file"]
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"data_dir": str(tmp_path / "d"), "database": database}), encoding="utf-8")
    return load_config(p)


def test_import_submodules_is_idempotent():
    registry.import_submodules("storageweb.core")
    registry.import_submodules("storageweb.core")


def test_alert_source(monkeypatch, cfg, tmp_path):
    monkeypatch.setattr(alerts, "_SOURCES", list(alerts._SOURCES))

    @alerts.source("prueba", order=1)
    def _prueba(ctx):
        return [alerts.alert("info", "prueba", "Hola", ctx.cfg["app_name"], "general", "Ver")]

    found = alerts.collect(cfg, {"data_dir": str(tmp_path)}, {})
    assert [a for a in found if a["key"] == "prueba"][0]["detail"] == "StorageWeb"
    with pytest.raises(ValueError):
        alerts.alert("rojo", "x", "", "", "", "")


def test_maintenance_task(monkeypatch, db_conn, cfg):
    monkeypatch.setattr(maintenance, "_TASKS", dict(maintenance._TASKS))
    runs = []

    @maintenance.task("prueba", every=lambda cfg: 2, order=1)
    def _prueba(conn, cfg):
        runs.append(1)

    @maintenance.task("rota", every=lambda cfg: 2, order=2)
    def _rota(conn, cfg):
        raise RuntimeError("falla")

    @maintenance.task("apagada", every=lambda cfg: 0)
    def _apagada(conn, cfg):
        raise AssertionError("no debe ejecutarse")

    done = maintenance.run_due(db_conn, cfg)
    assert done[:2] == ["prueba", "rota"] and "apagada" not in done  # la rota no para a las demás
    assert "cleanup" in done and runs == [1]
    assert maintenance.run_due(db_conn, cfg) == []  # nada hasta su intervalo
    assert {"prueba", "rota", "cleanup", "ipban_prune"} <= set(maintenance.state(db_conn))


def test_cli_command(monkeypatch, cfg, capsys):
    monkeypatch.setattr(cli_common, "COMMANDS", dict(cli_common.COMMANDS))
    monkeypatch.setattr("storageweb.cli.COMMANDS", cli_common.COMMANDS)

    def _args(p):
        p.add_argument("--veces", type=int, default=1)

    @cli_common.command("saluda", "Saluda", _args, order=5)
    def _saluda(cfg_, conn, args):
        print("hola " * args.veces)

    assert "saluda" in [c.name for c in commands()]
    assert "saluda" in build_parser().format_help()
    assert main(["--config", cfg["_config_path"], "saluda", "--veces", "2"]) == 0
    assert "hola hola" in capsys.readouterr().out


def test_search_provider(monkeypatch, make_app):
    from storageweb.web import search

    from tests.helpers import add_user, login

    monkeypatch.setattr(search, "_PROVIDERS", dict(search._PROVIDERS))
    monkeypatch.setattr(search, "_ACTIONS", list(search._ACTIONS))
    search.action("plus", "Plantar un árbol", "admin.index", words="jardín", order=1)

    @search.provider("arbol", "Árboles", order=1)
    def _arboles(terms, conn, cfg):
        return [search.item("arbol", "Roble", "parque", "/x")] if search.matches(terms, "roble encina") else []

    app = make_app()
    add_user(app, "root", role="admin")
    client = app.test_client()
    login(client, "root")
    results = client.get("/admin/search?format=json&q=roble").get_json()["results"]
    assert any(r["title"] == "Roble" and r["group"] == "Árboles" for r in results)
    results = client.get("/admin/search?format=json&q=jardin").get_json()["results"]
    assert any(r["title"] == "Plantar un árbol" for r in results)

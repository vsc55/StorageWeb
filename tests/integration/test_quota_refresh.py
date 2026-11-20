"""Uso de las cuotas (core/quota.py): se cuenta lo que escribe StorageWeb, se reconcilia en segundo plano con lo que
cambien otros (storage.quota_refresh_minutes), «medido hace X», y ubicaciones que no cuentan para la cuota."""
from __future__ import annotations

import json
import time

import pytest

from storageweb.core import backends, quota, storage
from storageweb.core.backends.local import LocalBackend
from storageweb.settings import ConfigError, load_config
from storageweb.i18n import set_locale
from tests.fakes import FakeS3

S3 = {"name": "bucket", "type": "s3", "bucket": "bucket", "prefix": "", "access_key": "AK", "secret_key": "S",
      "quota_exempt": True}


@pytest.fixture
def root(tmp_path):
    quota.clear()
    folder = tmp_path / "carpeta"
    folder.mkdir()
    (folder / "a.bin").write_bytes(b"x" * 1000)
    yield {"name": "c", "label": "C", "where": f"test:{folder}", "quota_mb": 1,
           "backend": LocalBackend(folder, tmp_path / "staging")}, folder
    quota.clear()
    quota.configure(60)


def _wait(r, seconds=5.0):
    deadline = time.monotonic() + seconds
    while quota.measuring(r) and time.monotonic() < deadline:
        time.sleep(0.02)


def _age(r, seconds):
    """Hace como si la medida tuviera ``seconds`` segundos."""
    hit = quota._cache[quota._key(r)]          # noqa: SLF001
    hit.measured -= seconds
    hit.at -= seconds


def test_counts_writes_and_reconciles_in_the_background(root):
    r, folder = root
    assert quota.usage(r) == (1000, True)                      # la primera vez, en el momento
    quota.record(r, 500)                                       # lo que escribe StorageWeb, al momento
    assert quota.usage(r) == (1500, True)
    (folder / "de-otro.bin").write_bytes(b"y" * 4000)          # otro programa escribe directamente
    assert quota.usage(r)[0] == 1500                           # todavía no: no se recorre en la petición
    _age(r, 3601)                                              # más vieja que storage.quota_refresh_minutes (60)
    assert quota.usage(r)[0] == 1500                           # se devuelve la que hay y se mide en segundo plano
    _wait(r)
    assert quota.usage(r) == (5000, True)


def test_invalidate_keeps_the_value_until_measured(root):
    r, folder = root
    quota.usage(r)
    (folder / "a.bin").unlink()                                # p. ej. al borrar una carpeta: no se sabe cuánto
    quota.invalidate(r)
    _wait(r)
    assert quota.usage(r) == (0, True)
    quota.configure(1)                                         # cada minuto
    _age(r, 61)
    (folder / "b.bin").write_bytes(b"z" * 10)
    quota.usage(r)
    _wait(r)
    assert quota.usage(r)[0] == 10


def test_status_says_when_it_was_measured(root):
    r, _folder = root
    set_locale("es")
    quota.usage(r)
    _age(r, 300)
    status = quota.status(r)
    assert status["measured_text"] == "hace 5 minutos" and status["measured_at"]
    _wait(r)


def test_locations_that_do_not_count(tmp_path, monkeypatch):
    monkeypatch.setitem(backends.CLIENT_FACTORIES, "s3", lambda loc: FakeS3())
    backends.clear_clients()
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"storage": {"locations": [S3, {**S3, "name": "otro", "quota_exempt": False}]}}),
                    encoding="utf-8")
    cfg = load_config(path)
    assert [loc["quota_exempt"] for loc in cfg["storage"]["locations"]] == [True, False]
    assert storage.make_root(cfg, "s", "S", "bucket", "x", quota_mb=50)["quota_mb"] == 0
    assert storage.make_root(cfg, "s", "S", "otro", "x", quota_mb=50)["quota_mb"] == 50
    backends.clear_clients()


def test_refresh_setting_is_validated(tmp_path):
    path = tmp_path / "config.json"
    for value in (0, 20000):
        path.write_text(json.dumps({"storage": {"quota_refresh_minutes": value}}), encoding="utf-8")
        with pytest.raises(ConfigError, match="quota_refresh_minutes"):
            load_config(path)

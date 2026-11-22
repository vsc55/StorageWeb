"""Carpetas con muchos elementos (storage.page_size, storage.listing_mode, files._listing): el explorador pinta
un trozo y el resto llega al bajar, por páginas o buscando con el filtro; la API sigue listando entera."""
from __future__ import annotations


import pytest

from storageweb.settings import ConfigError, load_config

from tests.helpers import signed_in, config_file


def _browser(make_app, home, mode, count=120):
    app = make_app({"storage": {"page_size": 50, "listing_mode": mode}})
    c, _ = signed_in(app, "ana", csrf_url=None)
    home.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (home / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
    (home / "Año especial.txt").write_text("x", encoding="utf-8")
    (home / "carpeta").mkdir()
    return c


def _rows(html: str) -> int:
    return html.count('class="file-row"')


def test_scroll_loads_the_rest_in_parts(make_app, home):
    c = _browser(make_app, home, "scroll")
    page = c.get("/f/home/").get_data(as_text=True)
    assert _rows(page) == 50 and 'id="listing-foot"' in page and 'data-mode="scroll"' in page
    assert "50 de 122 elementos" in page
    assert page.index('data-name="carpeta"') < page.index('data-name="f000.txt"')     # carpetas primero
    nxt = page.split('data-next="', 1)[1].split('"', 1)[0].replace("&amp;", "&")
    assert "rows=1" in nxt and "page=2" in nxt
    resp = c.get(nxt)
    assert _rows(resp.get_data(as_text=True)) == 50 and resp.headers["X-Total"] == "122"
    assert "<html" not in resp.get_data(as_text=True)                                  # solo las filas
    last = c.get(resp.headers["X-Next"])
    assert _rows(last.get_data(as_text=True)) == 22 and last.headers["X-Next"] == ""
    assert len(c.get("/f/home/", headers={"Accept": "application/json"}).get_json()["entries"]) == 122


def test_filter_searches_all_the_folder(make_app, home):
    c = _browser(make_app, home, "scroll")
    resp = c.get("/f/home/?rows=1&q=ANO")                                  # sin tildes ni mayúsculas
    assert _rows(resp.get_data(as_text=True)) == 1 and resp.headers["X-Total"] == "1"
    resp = c.get("/f/home/?rows=1&q=f1")                                   # f100…f119
    assert _rows(resp.get_data(as_text=True)) == 20 and resp.headers["X-Next"] == ""
    page = c.get("/f/home/?q=zzz").get_data(as_text=True)
    assert page.count("Ningún elemento coincide con el filtro.") == 2 and 'value="zzz"' in page


def test_pages(make_app, home):
    c = _browser(make_app, home, "pages")
    page = c.get("/f/home/?page=2&sort=name").get_data(as_text=True)
    assert _rows(page) == 50 and "Elementos 51–100 de 122" in page and "Página 2 de 3" in page
    assert 'rel="prev"' in page and 'rel="next"' in page and 'data-page="2"' in page
    assert _rows(c.get("/f/home/?page=99").get_data(as_text=True)) == 22             # más allá: la última


def test_search_mode_shows_only_the_first(make_app, home):
    c = _browser(make_app, home, "search")
    page = c.get("/f/home/?page=3").get_data(as_text=True)
    assert _rows(page) == 50 and 'data-next=""' in page and 'id="listing-pager"' not in page
    assert "escribe en el filtro" in page
    assert c.get("/f/home/?rows=1&q=f").headers["X-Next"] != ""            # filtrando, sí por trozos


def test_small_folders_are_whole(make_app, home):
    c = _browser(make_app, home, "pages", count=10)
    page = c.get("/f/home/").get_data(as_text=True)
    assert _rows(page) == 12 and 'id="listing-foot"' not in page


def test_settings_are_validated(tmp_path):
    def load(storage):
        path = config_file(tmp_path, {"storage": storage})
        return load_config(path)
    assert load({})["storage"]["listing_mode"] == "scroll"
    with pytest.raises(ConfigError, match="page_size"):
        load({"page_size": 10})
    with pytest.raises(ConfigError, match="listing_mode"):
        load({"listing_mode": "todo"})

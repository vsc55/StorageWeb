"""Los JavaScript de la web van partidos por función (el explorador en app.js + js/files/, las listas de etiquetas
en admin/tag-list.js): que ninguno quede sin cargar y que cada página cargue lo que usa."""
import re
from pathlib import Path

import storageweb

WEB = Path(storageweb.__file__).parent / "web"
JS = WEB / "static" / "js"
TEMPLATES = WEB / "templates"

SCRIPT = re.compile(r"filename=['\"](js/[^'\"]+\.js)['\"]")


def _templates():
    return {p: p.read_text(encoding="utf-8") for p in TEMPLATES.rglob("*.html")}


def test_every_script_is_loaded_by_some_page():
    loaded = {m for text in _templates().values() for m in SCRIPT.findall(text)}
    own = {p.relative_to(JS.parent).as_posix() for p in JS.rglob("*.js") if "vendor" not in p.parts}
    assert not own - loaded, f"nadie los carga: {sorted(own - loaded)}"
    assert not loaded - own - {p for p in loaded if p.startswith("js/vendor/")}, "una plantilla carga un JS que no existe"


def test_a_page_with_tag_lists_loads_their_script():
    for path, text in _templates().items():
        if "data-list" in text:
            assert "js/admin/tag-list.js" in text, f"{path.name} usa data-list sin admin/tag-list.js"


def test_the_file_browser_loads_its_modules_after_the_core():
    scripts = SCRIPT.findall((TEMPLATES / "browse.html").read_text(encoding="utf-8"))
    assert scripts[0] == "js/app.js", "app.js (crea SW.files) tiene que ir antes que sus módulos"
    assert set(scripts) == {"js/app.js", "js/files/upload.js", "js/files/transfer.js", "js/files/listing.js"}
    for module in ("transfer", "listing"):
        assert "window.SW.files" in (JS / "files" / f"{module}.js").read_text(encoding="utf-8")

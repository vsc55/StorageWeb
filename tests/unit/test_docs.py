"""La documentación no se queda atrás respecto al código."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

yaml = pytest.importorskip("yaml")

_spec = importlib.util.spec_from_file_location("gen_docs", ROOT / "tools" / "gen_docs.py")
gen_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_docs)


def test_every_option_is_described():
    from storageweb.settings.fields import FIELDS as DESCRIPTIONS

    documented = gen_docs.documented_keys()
    assert documented - set(DESCRIPTIONS) == set(), "opciones sin entrada en settings/fields.py"
    assert set(DESCRIPTIONS) - documented == set(), "descripciones de opciones que ya no existen"


def test_generated_reference_is_up_to_date():
    assert gen_docs.main(["--check"]) == 0, "ejecuta: python tools/gen_docs.py"


def test_openapi_matches_routes(app):
    spec = gen_docs.load_openapi()
    documented = {(path, method.upper()) for path, item in spec["paths"].items()
                  for method in item if method in ("get", "post", "put", "delete")}
    actual = set()
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/") or rule.rule in ("/healthz", "/connect/token"):  # las rutas JSON
            path = re.sub(r"<(?:[a-z]+:)?([a-z_]+)>", r"{\1}", rule.rule)
            actual |= {(path, m) for m in rule.methods - {"HEAD", "OPTIONS"}}
    assert actual == documented


def test_audit_actions_are_documented():
    pattern = re.compile(r"""(?:audit\.log\(\s*[\w()]+,\s*|_audit\(\s*)["']([a-z_]+)["']""")
    in_code = set()
    for path in (ROOT / "src" / "storageweb").rglob("*.py"):
        in_code |= set(pattern.findall(path.read_text(encoding="utf-8")))
    doc = (DOCS / "referencia" / "auditoria.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", doc, re.M))
    assert in_code, "no se encontraron acciones (¿ha cambiado la forma de llamar a audit.log?)"
    assert in_code - documented == set(), "acciones de auditoría sin documentar"


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda loader, suffix, node: None)


def _nav_files(nav) -> set[str]:
    out = set()
    for item in nav:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict):
            for value in item.values():
                out |= _nav_files(value) if isinstance(value, list) else {value}
    return out


def test_all_pages_in_nav():
    config = yaml.load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"), Loader=_Loader)
    in_nav = _nav_files(config["nav"])
    pages = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md")}
    assert pages - in_nav == set(), "páginas fuera de la navegación"
    assert in_nav - pages == set(), "la navegación apunta a páginas que no existen"

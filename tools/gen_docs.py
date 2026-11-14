#!/usr/bin/env python3
"""Genera las páginas de referencia de la documentación a partir del código.

    python tools/gen_docs.py          # regenera los ficheros
    python tools/gen_docs.py --check  # falla si algún fichero está desactualizado (CI)

Fuentes únicas de verdad:
    docs/referencia/configuracion.md  <- storageweb.settings (DEFAULTS + fields.FIELDS)
    docs/referencia/cli.md            <- storageweb.cli.build_parser()
    docs/referencia/api.md            <- docs/referencia/openapi.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from storageweb import i18n  # noqa: E402
from storageweb.settings.env import ENV_ALIASES, env_name  # noqa: E402
from storageweb.settings.fields import FIELDS  # noqa: E402
from storageweb.settings.defaults import (DEFAULTS, RUNTIME_SECTIONS,  # noqa: E402
                                          SECRET_FIELDS, SHARE_FIELDS)

# La documentación está en español: la ayuda de la CLI se genera con ese catálogo
i18n.set_locale("es")

REF = ROOT / "docs" / "referencia"
HEADER = "<!-- Generado por tools/gen_docs.py: no editar a mano -->\n\n"


# --------------------------------------------------------------------------- configuración

def config_leaves(tree: dict, prefix: str = "") -> list[tuple[str, object]]:
    """Claves hoja de DEFAULTS (un dict vacío, como role_mappings, cuenta como hoja)."""
    out = []
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out.extend(config_leaves(value, f"{path}."))
        else:
            out.append((path, value))
    return out


def documented_keys() -> set[str]:
    return {p for p, _ in config_leaves(DEFAULTS)} | {f"storage.shares[].{f}" for f in SHARE_FIELDS}


def _type(value) -> str:
    return {bool: "booleano", int: "entero", str: "texto", list: "lista", dict: "objeto"}.get(type(value), "—")


def _md(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return f"`{text}`"


def render_config() -> str:
    secrets = {".".join(p) for p in SECRET_FIELDS}
    lines = [HEADER, "# Referencia de configuración\n\n",
             "Todas las opciones, con su valor por defecto y su variable de entorno. Las rutas relativas se "
             "resuelven respecto a la carpeta donde está el `config.json`.\n\n",
             "Cada valor sale de la capa con más prioridad que lo fije, campo a campo: **predeterminado** < "
             "**ajustes web** < **`config.json`** < **variable de entorno**. Lo que fijan `config.json` o una "
             "variable queda bloqueado en la web.\n\n",
             "- **Web**: «Sí» = se puede cambiar desde las páginas de la administración (se aplica al momento) "
             "si no lo fijan `config.json` ni el entorno. «No» = de arranque: solo `config.json` o el entorno, "
             "y requiere reiniciar el servicio.\n",
             "- **Variable**: `STORAGEWEB_` + la ruta en mayúsculas con `__` entre niveles. Las listas y los "
             "objetos van en JSON (las listas de texto también separadas por comas); los booleanos, "
             "`true`/`false`.\n",
             "- Los valores secretos nunca se muestran en la web.\n\n"]
    leaves = config_leaves(DEFAULTS)
    sections: dict[str, list] = {}
    for path, value in leaves:
        sections.setdefault(path.split(".")[0], []).append((path, value))
    titles = {"app_name": "General", "default_locale": "General", "secret_key": "General", "data_dir": "General",
              "database": "General", "settings_profile": "General", "network": "Red (`network`)",
              "maintenance": "Mantenimiento (`maintenance`)", "branding": "Marca (`branding`)",
              "server": "Servidor (`server`)", "session": "Sesión (`session`)",
              "storage": "Almacenamiento (`storage`)", "permissions": "Permisos (`permissions`)",
              "auth": "Autenticación (`auth`)", "security": "Seguridad (`security`)"}
    grouped: dict[str, list] = {}
    for top, items in sections.items():
        grouped.setdefault(titles.get(top, top), []).extend(items)
    for title, items in grouped.items():
        lines.append(f"## {title}\n\n")
        lines.append("| Clave | Tipo | Por defecto | Web | Variable | Descripción |\n|---|---|---|---|---|---|\n")
        for path, value in items:
            web = "Sí" if path.split(".")[0] in RUNTIME_SECTIONS else "No"
            default = "*(secreto)*" if path in secrets and value else _md(value)
            env = f"`{env_name(path)}`" + "".join(f"<br>`{alias}`" for alias, target in ENV_ALIASES.items()
                                                  if target == path)
            lines.append(f"| `{path}` | {_type(value)} | {default} | {web} | {env} | {FIELDS[path].doc} |\n")
            if path == "storage.shares":
                for field in SHARE_FIELDS:
                    key = f"storage.shares[].{field}"
                    lines.append(f"| `{key}` | | | Sí | | {FIELDS[key].doc} |\n")
        lines.append("\n")
    lines.append("## Ejemplo\n\nEl fichero `config/config.example.json` del repositorio (instalado en "
                 "`/etc/storageweb/config.json` por los paquetes) solo trae lo de arranque y la plantilla de las "
                 "carpetas personales: así lo demás se puede cambiar desde la web.\n")
    return "".join(lines)


# --------------------------------------------------------------------------- CLI

def _action_name(action: argparse.Action) -> str:
    if action.option_strings:
        name = ", ".join(f"`{o}`" for o in action.option_strings)
        if action.nargs != 0:
            name += f" `{(action.metavar or action.dest).upper()}`"
        return name
    return f"`{action.metavar or action.dest}`"


def _action_help(action: argparse.Action) -> str:
    text = (action.help or "").replace("|", "\\|")
    if action.choices:
        text += f" Valores: {', '.join(f'`{c}`' for c in action.choices)}."
    if action.default not in (None, False, argparse.SUPPRESS) and action.nargs != 0:
        text += f" Por defecto: `{action.default}`."
    if action.required and action.option_strings:
        text += " Obligatorio."
    return text.strip()


def render_cli() -> str:
    from storageweb.cli import build_parser

    parser = build_parser()
    lines = [HEADER, "# Referencia de la CLI\n\n",
             "Comando `storageweb` (también `python -m storageweb`). En un servidor instalado con paquetes, "
             "usa `sudo storageweb-admin <comando>`, que lo ejecuta como el usuario del servicio y con "
             "`/etc/storageweb/config.json`.\n\n",
             "```\nstorageweb [--config RUTA] <comando> [opciones]\n```\n\n",
             "## Opciones globales\n\n| Opción | Descripción |\n|---|---|\n"]
    sub_action = None
    for action in parser._actions:  # noqa: SLF001 (API estable de argparse)
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            sub_action = action
        elif not isinstance(action, argparse._HelpAction):  # noqa: SLF001
            lines.append(f"| {_action_name(action)} | {_action_help(action)} |\n")
    lines.append("\n## Comandos\n\n| Comando | Descripción |\n|---|---|\n")
    helps = {a.dest: a.help for a in sub_action._choices_actions}  # noqa: SLF001
    for name in sub_action.choices:
        lines.append(f"| [`{name}`](#{name}) | {helps.get(name, '')} |\n")
    for name, sub in sub_action.choices.items():
        lines.append(f"\n### `{name}` {{#{name}}}\n\n{helps.get(name, '')}.\n\n")
        args = [a for a in sub._actions if not isinstance(a, argparse._HelpAction)]  # noqa: SLF001
        usage = " ".join([f"storageweb {name}"] + [
            (f"<{a.metavar or a.dest}>" if not a.option_strings else
             f"[{a.option_strings[-1]}{'' if a.nargs == 0 else ' ' + (a.metavar or a.dest).upper()}]")
            for a in args])
        lines.append(f"```\n{usage}\n```\n\n")
        if args:
            lines.append("| Argumento | Descripción |\n|---|---|\n")
            for a in args:
                lines.append(f"| {_action_name(a)} | {_action_help(a)} |\n")
    return "".join(lines)


# --------------------------------------------------------------------------- API

def load_openapi() -> dict:
    import yaml

    return yaml.safe_load((REF / "openapi.yaml").read_text(encoding="utf-8"))


def _resolve(spec: dict, obj: dict) -> dict:
    while isinstance(obj, dict) and "$ref" in obj:
        node = spec
        for part in obj["$ref"].lstrip("#/").split("/"):
            node = node[part]
        obj = node
    return obj


def _schema_fields(spec: dict, schema: dict) -> list[tuple[str, str, str]]:
    schema = _resolve(spec, schema)
    required = set(schema.get("required", []))
    out = []
    for name, prop in (schema.get("properties") or {}).items():
        prop = _resolve(spec, prop)
        kind = prop.get("type", "")
        if "enum" in prop:
            kind += " (" + ", ".join(map(str, prop["enum"])) + ")"
        out.append((f"`{name}`" + (" *" if name in required else ""), kind, prop.get("description", "")))
    return out


def render_api() -> str:
    spec = load_openapi()
    lines = [HEADER, f"# Referencia de la API\n\n{spec['info']['description'].strip()}\n\n",
             "La especificación completa está en [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1).\n\n",
             "| Método | Ruta | Descripción |\n|---|---|---|\n"]
    ops = []
    for path, item in spec["paths"].items():
        for method in ("get", "post", "put", "delete"):
            if method in item:
                ops.append((path, method, item[method], item.get("parameters", [])))
                lines.append(f"| `{method.upper()}` | `{path}` | {item[method]['summary']} |\n")
    for path, method, op, path_params in ops:
        lines.append(f"\n## `{method.upper()} {path}`\n\n**{op['summary']}.** {op.get('description', '').strip()}\n\n")
        security = op.get("security", spec.get("security", []))
        schemes = sorted({k for s in security for k in s})
        lines.append("Autenticación: " + (", ".join(f"`{s}`" for s in schemes) if schemes else "ninguna") + "\n\n")
        params = [_resolve(spec, p) for p in path_params + op.get("parameters", [])]
        if params:
            lines.append("| Parámetro | En | Descripción |\n|---|---|---|\n")
            for p in params:
                lines.append(f"| `{p['name']}`{' *' if p.get('required') else ''} | {p['in']} | "
                             f"{p.get('description', '')} |\n")
            lines.append("\n")
        body = op.get("requestBody")
        if body:
            for ctype, media in body["content"].items():
                fields = _schema_fields(spec, media.get("schema", {}))
                lines.append(f"Cuerpo (`{ctype}`)" + (":\n\n" if fields else ": datos binarios.\n\n"))
                if fields:
                    lines.append("| Campo | Tipo | Descripción |\n|---|---|---|\n")
                    lines.extend(f"| {n} | {t} | {d} |\n" for n, t, d in fields)
                    lines.append("\n")
        lines.append("| Respuesta | Descripción |\n|---|---|\n")
        for code, resp in op["responses"].items():
            resp = _resolve(spec, resp)
            detail = resp["description"]
            content = resp.get("content", {}).get("application/json")
            if content:
                fields = _schema_fields(spec, content["schema"])
                if fields:
                    detail += " — " + ", ".join(n.replace(" *", "") for n, _, _ in fields)
            lines.append(f"| `{code}` | {detail} |\n")
    lines.append("\n`*` = obligatorio.\n")
    return "".join(lines)


# --------------------------------------------------------------------------- main

TARGETS = {
    REF / "configuracion.md": render_config,
    REF / "cli.md": render_cli,
    REF / "api.md": render_api,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="No escribe; falla si hay diferencias")
    args = ap.parse_args(argv)
    stale = []
    for path, render in TARGETS.items():
        content = render()
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            print(f"actualizado {path.relative_to(ROOT).as_posix()}")
    if stale:
        print("Documentación desactualizada (ejecuta: python tools/gen_docs.py):\n  " + "\n  ".join(stale),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

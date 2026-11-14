"""Acceso → Carpetas compartidas (solo rol admin): cada carpeta con quién entra y con qué permiso.

Edita ``storage.shares`` como el resto de ajustes (se guarda la diferencia con config.json y se
aplica al guardar). La vista por grupos de lo mismo es la matriz de accesos (``groups.matrix_view``).
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ...core import groups as group_core
from ...core import shares as share_core
from ...db.repositories import audit, users
from ...db.repositories import groups as group_repo
from ...i18n import _
from ..context import get_db, runtime, settings
from ..guards import admin_required, client_ip
from .groups import entra_names
from .settings import save_partial

bp = Blueprint("access", __name__, url_prefix="/admin/access")


def _audit(action: str, target: str | None = None, detail: str | None = None) -> None:
    audit.log(get_db(), action, target, username=g.user["username"], ip=client_ip(), detail=detail)


def _shares() -> list[dict]:
    return settings()["storage"]["shares"]


def _directory() -> dict:
    """Nombres visibles de grupos y usuarios para las entradas de acceso y las sugerencias."""
    rows = group_repo.list_all(get_db())
    groups: dict[str, dict] = {}
    for row in rows:
        info = {"label": group_core.label(row), "source": row["source"], "members": row["members"]}
        groups[row["name"]] = info
        if row["external_id"]:
            groups[row["external_id"].lower()] = info
    refs = {ref for s in _shares() for ref in s["groups"] if ref not in groups}
    for ref, name in entra_names(sorted(refs)).items():
        groups[ref] = {"label": name, "source": "entra", "members": None}
    people = {u["username"].lower(): u["display_name"] or u["username"] for u in users.list_all(get_db())}
    return {"groups": groups, "users": people, "group_rows": rows}


def _describe(share: dict, directory: dict) -> list[dict]:
    result = []
    for entry in share_core.entries(share):
        if entry["kind"] == "group":
            info = directory["groups"].get(entry["ref"])
            entry = {**entry, "label": info["label"] if info else entry["ref"], "known": bool(info)}
        elif entry["kind"] == "user":
            entry = {**entry, "label": directory["users"].get(entry["ref"], entry["ref"]),
                     "known": entry["ref"] in directory["users"]}
        else:
            entry = {**entry, "label": _("All users"), "known": True}
        result.append(entry)
    return result


def _form_share(original: dict | None) -> dict:
    """La carpeta tal como viene del formulario (sin validar: lo hace el cargador de ajustes)."""
    f = request.form
    items = [{"kind": k, "ref": r, "level": lv}
             for k, r, lv in zip(f.getlist("entry_kind"), f.getlist("entry_ref"), f.getlist("entry_level"))
             if lv != "none"]
    if f.get("add_ref", "").strip() or f.get("add_kind") == "all":
        items.append({"kind": f.get("add_kind", "group"), "ref": f.get("add_ref", ""),
                      "level": f.get("add_level", "write")})
    base = {"name": f.get("name", original["name"] if original else "").strip(),
            "label": f.get("label", "").strip(), "path": f.get("path", "").strip(),
            "read_only": f.get("read_only") == "on"}
    return share_core.with_entries(base, items)


def _render_folder(share: dict, original: str | None, status: int = 200, error: str | None = None):
    directory = _directory()
    title = (share.get("label") or share["name"]) if original else _("New shared folder")
    return render_template("admin/access/folder.html", share=share, original=original, title=title,
                           entries=_describe(share, directory), directory=directory, error=error,
                           exists=bool(share.get("path")) and Path(share["path"]).exists(),
                           changed="storage.shares" in runtime().changed_paths(get_db()),
                           LEVEL_LABELS=share_core.LEVEL_LABELS, ENTRY_KIND_LABELS=share_core.KIND_LABELS), status


def _store(original: str | None):
    """Guarda la carpeta del formulario. Devuelve la respuesta (redirección o el formulario con el error)."""
    try:
        share = _form_share(share_core.find(_shares(), original) if original else None)
        new_list = share_core.replace(_shares(), original, share)
    except share_core.ShareError as exc:
        draft = {"name": request.form.get("name", original or ""), "label": request.form.get("label", ""),
                 "path": request.form.get("path", ""), "read_only": False, "users": [], "read_only_users": [],
                 "groups": [], "read_only_groups": []}
        return _render_folder(draft, original, 400, exc.message)
    _draft, error = save_partial(lambda: {"storage": {"shares": new_list}})
    if error:
        return _render_folder(share, original, 400, str(error))
    if original is None:
        _audit("share_created", share["name"], share["path"])
        flash(_("Shared folder «%(label)s» created.", label=share["label"] or share["name"]), "info")
    else:
        _audit("share_updated", share["name"], _entries_detail(share))
        flash(_("Shared folder «%(label)s» saved.", label=share["label"] or share["name"]), "info")
    return redirect(url_for("access.folders") + f"#share-{share['name']}")


def _entries_detail(share: dict) -> str:
    parts = [f"{e['ref']}={e['level']}" for e in share_core.entries(share)]
    return (", ".join(parts) + (" (read_only)" if share["read_only"] else ""))[:500]


@bp.route("/")
@admin_required
def index():
    return redirect(url_for("access.folders"))


@bp.route("/folders")
@admin_required
def folders():
    directory = _directory()
    rows = [{"share": s, "entries": _describe(s, directory), "exists": Path(s["path"]).exists()} for s in _shares()]
    return render_template("admin/access/folders.html", rows=rows, LEVEL_LABELS=share_core.LEVEL_LABELS,
                           changed="storage.shares" in runtime().changed_paths(get_db()),
                           create_shares=settings()["storage"]["create_shares"])


@bp.route("/folders/new", methods=["GET", "POST"])
@admin_required
def folder_new():
    if request.method == "POST":
        return _store(None)
    return _render_folder({"name": "", "label": "", "path": "", "read_only": False, "users": [],
                           "read_only_users": [], "groups": [], "read_only_groups": []}, None)


@bp.route("/folders/<name>", methods=["GET", "POST"])
@admin_required
def folder(name: str):
    share = share_core.find(_shares(), name)
    if share is None:
        abort(404)
    if request.method == "POST":
        return _store(name)
    return _render_folder(share, name)


@bp.route("/folders/<name>/delete", methods=["POST"])
@admin_required
def folder_delete(name: str):
    share = share_core.find(_shares(), name)
    if share is None:
        abort(404)
    _draft, error = save_partial(lambda: {"storage": {"shares": share_core.remove(_shares(), name)}})
    if error:
        flash(_("The changes were not saved: %(error)s", error=error), "error")
        return redirect(url_for("access.folder", name=name))
    _audit("share_deleted", name, share["path"])
    flash(_("Shared folder «%(label)s» removed. Its files are still on the server.", label=share["label"]), "info")
    return redirect(url_for("access.folders"))

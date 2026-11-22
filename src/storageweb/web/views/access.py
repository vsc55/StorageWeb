"""Acceso → Carpetas compartidas (solo rol admin): cada carpeta con quién entra y con qué permiso.

Edita ``storage.shares`` como el resto de ajustes (se guarda la diferencia con config.json y se
aplica al guardar). La vista por grupos de lo mismo es la matriz de accesos (``groups.matrix_view``).
"""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ...core import groups as group_core
from ...core import locations as location_core
from ...core import quota, storage
from ...core import shares as share_core
from ...db.repositories import users
from ...db.repositories import groups as group_repo
from ...i18n import _, _l, format_size
from ..context import get_db, runtime, settings
from ..guards import admin_required, audit_event
from .. import search
from .groups import directory_lookup
from .settings.common import save_partial
from ...settings.layers import CONFIG_ORIGINS

bp = Blueprint("access", __name__, url_prefix="/admin/access")


_audit = audit_event


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
    for ref, (source, name) in directory_lookup(sorted(refs)).items():
        groups[ref] = {"label": name, "source": source, "members": None}
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
            "label": f.get("label", "").strip(), "location": f.get("location", "").strip(),
            "path": f.get("path", "").strip(),
            "read_only": f.get("read_only") == "on",
            "quota_mb": f.get("quota_mb", "").strip() or 0}  # lo valida el cargador de ajustes
    return share_core.with_entries(base, items)


def entity_lock(kind: str, item: dict | None) -> str:
    """Si la carpeta (o ubicación) está fijada en config.json o en el entorno: el mensaje; se ve pero no se edita.
    Las de la web (tabla ``shares``) se editan."""
    if not item or item.get("origin") not in CONFIG_ORIGINS:
        return ""
    return runtime()._entity_lock_message(kind, item["name"], item["origin"])


def lock_context(kind: str, item: dict | None = None) -> dict:
    """Lo que necesitan las plantillas de la lista y la ficha (``shares`` o ``locations``) para el aviso de fijado."""
    return {f"{kind}_origin": None, "locked_message": entity_lock(kind, item)}


def refuse_if_locked(kind: str, item: dict | None, back_endpoint: str):
    """Si ``item`` está fijado en config.json o el entorno: el aviso y de vuelta a la lista; si no, ``None``."""
    notice = entity_lock(kind, item)
    if notice:
        flash(notice, "error")
        return redirect(url_for(back_endpoint))
    return None


def _lock_context(share: dict | None = None) -> dict:
    return lock_context("shares", share)


def _refuse_if_locked(share: dict | None):
    return refuse_if_locked("shares", share, "access.folders")


def _share_usage(name: str | None) -> dict | None:
    """Uso y cuota de una carpeta compartida ya guardada (para la ficha)."""
    saved = share_core.find(settings()["storage"]["shares"], name) if name else None
    if saved is None:
        return None
    root = storage.make_root(settings(), saved["name"], saved["label"], saved.get("location", ""), saved["path"],
                             quota_mb=saved.get("quota_mb", 0))
    used, complete = quota.usage(root)
    return {"used": format_size(used), "complete": complete, "quota": quota.status(root)}


def _render_folder(share: dict, original: str | None, status: int = 200, error: str | None = None):
    directory = _directory()
    title = (share.get("label") or share["name"]) if original else _("New shared folder")
    return render_template("admin/access/folder.html", share=share, original=original, title=title,
                           cfg_quota_enforce=settings()["storage"]["quota_enforce"],
                           entries=_describe(share, directory), directory=directory, error=error,
                           exists=location_core.local_exists(share.get("location", ""), share.get("path", "")),
                           where=location_core.where(settings(), share.get("location", ""), share.get("path", "")),
                           locations=settings()["storage"]["locations"], usage=_share_usage(original),
                           **_lock_context(share_core.find(_shares(), original) if original else None),
                           LEVEL_LABELS=share_core.LEVEL_LABELS,
                           ENTRY_KIND_LABELS=share_core.KIND_LABELS), status


def _store(original: str | None):
    """Guarda la carpeta del formulario. Devuelve la respuesta (redirección o el formulario con el error)."""
    refused = _refuse_if_locked(share_core.find(_shares(), original) if original else None)
    if refused:
        return refused
    try:
        share = _form_share(share_core.find(_shares(), original) if original else None)
        new_list = share_core.replace(_shares(), original, share)
    except share_core.ShareError as exc:
        draft = {"name": request.form.get("name", original or ""), "label": request.form.get("label", ""),
                 "location": request.form.get("location", ""), "path": request.form.get("path", ""), "read_only": False, "users": [], "read_only_users": [],
                 "groups": [], "read_only_groups": []}
        return _render_folder(draft, original, 400, exc.message)
    _draft, error = save_partial(lambda: {"storage": {"shares": new_list}}, strict=True)
    if error:
        return _render_folder(share, original, 400, str(error))
    if original is None:
        _audit("share_created", share["name"], location_core.where(settings(), share["location"], share["path"]))
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
    cfg = settings()
    rows = [{"share": s, "entries": _describe(s, directory), "where": location_core.where(cfg, s["location"], s["path"]),
             "exists": location_core.local_exists(s["location"], s["path"])} for s in _shares()]
    return render_template("admin/access/folders.html", rows=rows, LEVEL_LABELS=share_core.LEVEL_LABELS,
                           **_lock_context(), create_shares=settings()["storage"]["create_shares"])


@bp.route("/folders/new", methods=["GET", "POST"])
@admin_required
def folder_new():
    if request.method == "POST":
        return _store(None)
    return _render_folder({"name": "", "label": "", "location": "", "path": "", "read_only": False, "users": [],
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
    refused = _refuse_if_locked(share)
    if refused:
        return refused
    _draft, error = save_partial(lambda: {"storage": {"shares": share_core.remove(_shares(), name)}}, strict=True)
    if error:
        flash(_("The changes were not saved: %(error)s", error=error), "error")
        return redirect(url_for("access.folder", name=name))
    _audit("share_deleted", name, location_core.where(settings(), share["location"], share["path"]))
    flash(_("Shared folder «%(label)s» removed. Its files are still on the server.", label=share["label"]), "info")
    return redirect(url_for("access.folders"))


search.action("folder", _l("New shared folder"), "access.folder_new",
              words="crear carpeta compartida share add create", order=30)


@search.provider("share", _l("Shared folders"), order=30)
def _search_shares(terms, conn, cfg):
    return [search.item("share", s["label"], f"/f/{s['name']}", url_for("access.folder", name=s["name"]),
                        icon="folder")
            for s in cfg["storage"]["shares"] if search.matches(terms, s["label"], s["name"], s["path"])]

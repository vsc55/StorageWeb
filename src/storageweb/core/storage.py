"""Raíces de almacenamiento (home + carpetas compartidas) y operaciones de directorio.

Cada raíz lleva su ``backend`` (disco local, S3 o SMB: ver ``core/backends``); el resto del código
trabaja con rutas relativas a la raíz y no sabe dónde están los archivos.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import patterns
from ..db.repositories import users as users_repo
from ..db.repositories.users import groups_of
from ..i18n import _, format_datetime, format_size
from ..settings import server_paths
from . import backends
from .groups import ADMINS_GROUP
from .permissions import ADMIN
from .security import UPLOAD_TMP_PREFIX, PathError, safe_username_for_path
from ..settings.errors import UserError


HOME = "home"       # el nombre de la raíz de la carpeta personal: la de cada uno


class RootNotFound(Exception):
    pass


class EntryError(UserError):
    """Una ruta que no vale para señalarla (un favorito, un enlace para compartir)."""


def existing_entry(cfg: dict, root: dict, rel: str):
    """``(ruta limpia, Entry o None si no hay nada)`` en ``root``, para crear algo que la señale. :class:`EntryError`
    si la ruta no es válida, está oculta para todos (``storage.hidden``) o el almacenamiento falla."""
    try:
        rel = backends.clean_rel(rel)
    except PathError as exc:
        raise EntryError(_("That path is not valid.")) from exc
    if is_hidden(cfg, rel):
        raise EntryError(_("That path is hidden for everyone (Hidden for everyone)."))
    try:
        return rel, root["backend"].stat(rel)
    except backends.BackendError as exc:
        raise EntryError(exc.message) from exc


def home_owner(user, *roots: str) -> int | None:
    """Para lo que se guarda por ruta (favoritos, enlaces) y hay que seguir al renombrar, mover o borrar: la carpeta
    personal es de cada usuario, así que en ella solo cambian las filas de quien hace la operación (su id);
    en una carpeta compartida, las de todos (``None``)."""
    return user["id"] if HOME in roots else None


def effective_groups(user) -> set[str]:
    """Los grupos de la persona (los suyos y los del proveedor) y, si es administradora, el de serie ``admins``."""
    names = groups_of(user)
    if user["role"] == ADMIN:
        names.add(ADMINS_GROUP)  # grupo de serie: lo da el rol
    return names


def home_path_for(user, cfg: dict) -> str:
    """Carpeta personal: ruta en el disco o, con ``home_location``, ruta dentro de esa ubicación."""
    if user["home_path"]:
        return user["home_path"]
    tmpl = cfg["storage"]["home_template"]
    return tmpl.replace("{username}", safe_username_for_path(user["username"]))


def home_after_rename(user, new_username: str, cfg: dict) -> tuple[dict, str]:
    """Qué pasa con la carpeta personal cuando cambia el nombre de la cuenta (p. ej. el UPN en Entra ID).

    Devuelve (campos para la cuenta, «moved» | «kept» | ""). Con ruta propia no cambia nada. Con la plantilla, si
    la carpeta antigua existe: en el disco del servidor se renombra a la nueva si esta no existe; si no se puede
    (o está en una ubicación remota), la cuenta se queda con la antigua como ruta propia, para no perder nada."""
    if user["home_path"]:
        return {}, ""
    old = home_path_for(user, cfg)
    new = home_path_for({**dict(user), "username": new_username}, cfg)
    if old == new:
        return {}, ""
    location = cfg["storage"].get("home_location", "")
    try:
        exists = make_root(cfg, "home", "", location, old)["backend"].root_exists()
    except Exception:  # noqa: BLE001 (en la duda, se conserva la carpeta antigua)
        exists = True
    if not exists:
        return {}, ""
    if not location:
        src, dst = Path(old), Path(new)
        if not dst.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
                return {}, "moved"
            except OSError:
                pass
    return {"home_path": old}, "kept"


def make_root(cfg: dict, name: str, label: str, location: str, path: str, **extra) -> dict:
    """Raíz con su backend. ``path`` (Path) solo existe si está en el disco del servidor."""
    loc = backends.find_location(cfg, location) if location else None
    staging = backends.staging_dir(cfg)
    allowed = cfg["storage"].get("allowed_folders") or []
    if location and loc is None:
        backend = backends.UnavailableBackend(_("The storage location %(name)s does not exist.", name=location),
                                              staging)
    elif not location and not server_paths.permitted(path, allowed):
        # Una carpeta del disco que ya existía antes de restringirlas (o una carpeta personal propia): no se abre
        backend = backends.UnavailableBackend(
            _("This folder is a network path outside the allowed server folders.") if server_paths.network_path(path)
            else _("This folder is outside the allowed server folders."), staging)
    else:
        try:
            backend = backends.backend_for(loc, path, staging)
        except PathError:
            backend = backends.UnavailableBackend(_("Invalid path: %(path)s", path=path), staging)
    if loc is not None and loc.get("quota_exempt"):
        extra["quota_mb"] = 0     # «No cuenta para la cuota»: sus carpetas no tienen
    return {**extra, "name": name, "label": label, "location": location, "backend": backend,
            "path": None if location else Path(path), "where": f"{location}:{path}"}


def disk_folders(conn, cfg: dict, allowed: list[str] | None = None) -> list[dict]:
    """Las carpetas del disco del servidor que se usan (la de las carpetas personales, las compartidas sin ubicación
    y las carpetas personales propias) y si están dentro de ``allowed`` (por defecto, ``storage.allowed_folders``):
    ``{"kind": home|share|user, "name", "label", "path", "base"}`` (``base`` None = fuera)."""
    allowed = cfg["storage"].get("allowed_folders") or [] if allowed is None else allowed

    def row(kind, name, label, path):
        base = server_paths.base_of(path, allowed) if allowed else ""
        return {"kind": kind, "name": name, "label": label, "path": path, "base": base}

    found = []
    if not cfg["storage"].get("home_location"):
        template = cfg["storage"]["home_template"]
        head = template.split("{username}")[0] or template
        found.append(row("home", "", _("Personal folders"), head))
        trimmed = head.rstrip("/\\")
        if len(trimmed) > 2:            # sin la barra final al mostrarla («C:\» y «/» se quedan como están)
            found[-1]["path"] = trimmed
        found += [row("user", u["uid"], u["username"], u["home_path"]) for u in users_repo.with_own_home(conn)]
    found += [row("share", s["name"], s.get("label") or s["name"], s["path"])
              for s in cfg["storage"].get("shares", []) if not s.get("location")]
    return found


def home_quota_mb(user, cfg: dict) -> int:
    """Cuota de la carpeta personal (0 = sin cuota): la del usuario si tiene; si no, la de sus grupos
    (``storage.group_quotas``: si alguno no tiene límite, ninguno; si no, la mayor); si no, la de por defecto."""
    try:
        value = user["quota_mb"]
    except (KeyError, IndexError):
        value = None
    if value is not None:
        return int(value)
    by_group = cfg["storage"].get("group_quotas") or {}
    if by_group:
        names = effective_groups(user)
        found = [int(by_group[n]) for n in names if n in by_group]
        if found:
            return 0 if 0 in found else max(found)
    return int(cfg["storage"].get("home_quota_mb", 0) or 0)


def available_roots(user, cfg: dict) -> list[dict]:
    """Raíces accesibles: su home + las carpetas compartidas permitidas por usuario o grupo."""
    roots = [make_root(cfg, "home", _("My folder"), cfg["storage"].get("home_location", ""), home_path_for(user, cfg),
                       read_only=False, quota_mb=home_quota_mb(user, cfg))]
    uname = user["username"].lower()
    ugroups = effective_groups(user)
    for share in cfg["storage"]["shares"]:
        level = share_access(share, uname, ugroups)
        if level != "none":
            roots.append(make_root(cfg, share["name"], share["label"], share.get("location", ""), share["path"],
                                   **{k: v for k, v in share.items() if k not in ("name", "label", "location", "path", "read_only")},
                                   read_only=level == "read"))
    return roots


def share_access(share: dict, uname: str, ugroups: set[str]) -> str:
    """Nivel (``none``/``read``/``write``) que da la carpeta a un usuario con esos grupos.

    Se entra por nombre, por ``*`` (todos) o por grupo; se puede escribir si **alguna** de esas vías
    no es de solo lectura, salvo que la carpeta entera lo sea.
    """
    ro_users = set(share.get("read_only_users", []))
    paths = []  # una entrada por vía de acceso: True si permite escribir
    if uname in share["users"]:
        paths.append(uname not in ro_users)
    if "*" in share["users"]:
        paths.append("*" not in ro_users)
    ro_groups = set(share.get("read_only_groups", []))
    paths += [g not in ro_groups for g in ugroups.intersection(share["groups"])]
    if not paths:
        return "none"
    return "write" if any(paths) and not share["read_only"] else "read"


def explain_access(user, cfg: dict, group_labels: dict[str, str] | None = None) -> list[dict]:
    """Carpetas que ve el usuario, con su nivel (``read``/``write``) y por qué.

    Usa las mismas reglas que :func:`available_roots`; ``group_labels`` traduce identificadores de
    grupo (o Object IDs) a su nombre visible.
    """
    labels = group_labels or {}
    uname = user["username"].lower()
    ugroups = effective_groups(user)
    result = [{"name": "home", "label": _("My folder"), "level": "write", "reasons": [_("personal folder")]}]
    for root in available_roots(user, cfg)[1:]:
        share = next(s for s in cfg["storage"]["shares"] if s["name"] == root["name"])
        reasons = []
        ro_users = set(share.get("read_only_users", []))
        ro_groups = set(share.get("read_only_groups", []))
        if "*" in share["users"]:
            reasons.append(_("open to all users") + (_(" (read only)") if "*" in ro_users else ""))
        if uname in share["users"]:
            reasons.append(_("by user name") + (_(" (read only)") if uname in ro_users else ""))
        for ref in sorted(ugroups.intersection(share["groups"])):
            reasons.append(_("group %(name)s", name=labels.get(ref, ref))
                           + (_(" (read only)") if ref in ro_groups else ""))
        if share["read_only"]:
            reasons.append(_("read-only folder"))
        result.append({"name": root["name"], "label": root["label"],
                       "level": "read" if root["read_only"] else "write", "reasons": reasons})
    return result


def find_root(user, cfg: dict, name: str) -> dict:
    for root in available_roots(user, cfg):
        if root["name"] != name:
            continue
        backend = root["backend"]
        try:
            exists = backend.root_exists()
        except backends.BackendError as exc:
            raise RootNotFound(exc.message) from exc
        if not exists:
            storage = cfg["storage"]
            create = storage["create_home"] if name == "home" else storage["create_shares"]
            if not create:
                raise RootNotFound(_("The configured folder does not exist on the server."))
            try:
                backend.ensure_root(home=name == "home")
            except backends.BackendError as exc:
                raise RootNotFound(exc.message) from exc
        return root
    raise RootNotFound("")


SORT_KEYS = ("name", "size", "mtime")


def is_hidden(cfg: dict, rel: str, is_dir: bool = True) -> bool:
    """¿Está oculta para todos (``storage.hidden``)? Sin saber si es carpeta, se trata como tal (lo más estricto)."""
    return bool(rel) and patterns.of(cfg)(rel, is_dir)


def check_visible_name(cfg: dict, rel: str) -> None:
    """Para crear o renombrar: un nombre oculto para todos no se puede usar. Lanza ValueError."""
    if is_hidden(cfg, rel):
        raise ValueError(_("«%(name)s» is not allowed here.", name=backends.name_of(rel)))


def list_directory(root: dict, rel: str, show_hidden: bool, sort: str = "name",
                   descending: bool = False, hidden: Callable[[str, bool], bool] | None = None) -> list[dict]:
    """Contenido de una carpeta: las carpetas siempre primero, luego ordenado por ``sort``. ``hidden``: lo que
    no se muestra a nadie (``patterns.of(cfg)``)."""
    base_rel = backends.clean_rel(rel)
    entries = []
    for entry in root["backend"].listdir(base_rel):
        if entry.name.startswith(UPLOAD_TMP_PREFIX):
            continue
        if not backends.is_safe_name(entry.name):  # un servidor remoto no puede colar «..» ni «a/b»
            continue
        if not show_hidden and entry.name.startswith("."):
            continue
        if hidden and hidden(f"{base_rel}/{entry.name}".lstrip("/"), entry.is_dir):
            continue
        ext = "" if entry.is_dir else Path(entry.name).suffix.lstrip(".").upper()
        entries.append({
            "name": entry.name,
            "is_dir": entry.is_dir,
            "ext": ext if len(ext) <= 8 else "",
            "bytes": 0 if entry.is_dir else entry.size,
            "ts": entry.mtime,
            "size": "" if entry.is_dir else format_size(entry.size),
            "mtime": format_datetime(datetime.fromtimestamp(entry.mtime)) if entry.mtime else "",
            "rel": f"{base_rel}/{entry.name}".lstrip("/"),
        })
    if sort not in SORT_KEYS:
        sort = "name"
    keys = {"name": lambda e: e["name"].lower(), "size": lambda e: e["bytes"], "mtime": lambda e: e["ts"]}
    entries.sort(key=lambda e: (e["name"].lower(),))  # desempate estable por nombre
    entries.sort(key=keys[sort], reverse=descending)
    entries.sort(key=lambda e: not e["is_dir"])        # carpetas primero (sort estable)
    return entries


TREE_MAX_LEVELS = 8


def folder_tree(root: dict, rel: str, show_hidden: bool, hidden: Callable[[str, bool], bool] | None = None,
                current: list[dict] | None = None) -> list[dict]:
    """El árbol de carpetas del panel lateral, como el Explorador: en cada nivel del camino hasta ``rel``, todas
    sus carpetas (las hermanas también), con las del camino desplegadas. Filas en orden de pintado:
    ``{name, rel, level, open, current}``. ``current``: el listado de ``rel`` si ya se tiene (no se repite).

    Una carpeta de encima que no se pueda listar (sin permiso, almacenamiento remoto caído) o más honda que
    TREE_MAX_LEVELS solo aporta su paso del camino."""
    parts = rel.split("/") if rel else []
    rows: list[dict] = []

    def level(dir_rel: str, depth: int) -> None:
        on_path = parts[depth - 1] if depth <= len(parts) else None   # la siguiente carpeta del camino
        dirs = None
        if depth <= TREE_MAX_LEVELS:
            try:
                listing = current if dir_rel == rel and current is not None else \
                    list_directory(root, dir_rel, show_hidden, hidden=hidden)
                dirs = sorted((e for e in listing if e["is_dir"]), key=lambda e: e["name"].lower())
            except (backends.BackendError, PermissionError, OSError, PathError):
                dirs = None
        if dirs is None:  # solo el camino
            dirs = [{"name": on_path, "rel": "/".join(parts[:depth])}] if on_path else []
        for e in dirs:
            opened = on_path is not None and e["name"] == on_path
            rows.append({"name": e["name"], "rel": e["rel"], "level": depth, "open": opened,
                         "current": opened and depth == len(parts)})
            if opened and depth < len(parts) + 1:
                level(e["rel"], depth + 1)

    level("", 1)
    return rows


SPACE_WARN, SPACE_DANGER = 80, 95  # % de uso a partir del que se avisa (naranja) o alarma (rojo)


def space_of(root: dict, rel: str = "") -> dict | None:
    """El espacio del almacenamiento de una carpeta, listo para mostrar: ``{"unlimited": True}`` o
    ``{"total", "free", "used", "percent", "level", "free_text", "total_text"}``; ``None`` si no se sabe."""
    try:
        space = root["backend"].space(rel)
    except Exception:  # noqa: BLE001 (mostrar el espacio nunca debe romper la página)
        return None
    if not space:
        return None
    if space.get("unlimited"):
        return {"unlimited": True}
    total, free = space.get("total") or 0, space.get("free")
    if not total or free is None:
        return None
    used = max(total - free, 0)
    percent = min(100, round(used * 100 / total))
    return {"total": total, "free": free, "used": used, "percent": percent,
            "level": "danger" if percent >= SPACE_DANGER else "warn" if percent >= SPACE_WARN else "ok",
            "free_text": format_size(free), "total_text": format_size(total)}


def breadcrumbs(rel: str) -> list[dict]:
    crumbs, acc = [], []
    for part in rel.split("/") if rel else []:
        acc.append(part)
        crumbs.append({"name": part, "rel": "/".join(acc)})
    return crumbs

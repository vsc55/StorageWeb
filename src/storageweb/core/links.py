"""Enlaces para compartir un archivo o una carpeta con gente de fuera, sin cuenta (``/s/<token>``).

* **Quién**: quien tenga el permiso ``share`` (rol; los administradores siempre) en esa carpeta de StorageWeb, con
  ``sharing.links`` encendido. Un enlace de descarga pide además poder descargar; un **buzón** (``upload``: solo
  subir, sin ver lo que hay; solo carpetas, si ``sharing.upload_links``), poder subir.
* **Al abrirlo** cuentan los permisos de AHORA de quien lo creó (:func:`resolve`): si se desactiva su cuenta, pierde
  la carpeta o el permiso, el enlace deja de funcionar. Nunca da más de lo que esa persona puede.
* **El token**: 24 bytes aleatorios (192 bits). Se guarda su SHA-256 (para encontrarlo) y, cifrado con la clave de
  los secretos, el token (para que su dueño pueda volver a copiar el enlace); con la base de datos sola no se abre.
* **Límites**: caducidad (``sharing.default_days``, como mucho ``sharing.max_days``), contraseña opcional (obligatoria
  con ``sharing.require_password``) y número de descargas (cada archivo o ZIP cuenta una, de forma atómica).
* Sigue al archivo si se renombra o se mueve desde StorageWeb y se borra con él (:func:`moved`, :func:`deleted`,
  como los favoritos: los de la carpeta personal, solo los de quien hace la operación).

Sin Flask.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from sqlite3 import Connection

from werkzeug.security import check_password_hash, generate_password_hash

from ..db.repositories import share_links as repo
from ..db.repositories import users as user_repo
from ..i18n import _, _l, ngettext
from ..settings import secretbox
from . import backends, maintenance, storage
from .permissions import effective_for_root, permissions_for
from .security import PathError
from ..settings.errors import UserError
from ..clock import iso_ago, iso_in, utcnow
from ..text import offered_days, sha256_hex

TOKEN_BYTES = 24
MODES = ("download", "upload")
MODE_LABELS = {"download": _l("View and download"), "upload": _l("Upload only (drop box)")}
PASSWORD_MIN = 8
MAX_DOWNLOADS = 100000
KEEP_EXPIRED_DAYS = 30


class LinkError(UserError):
    pass


def options(cfg: dict) -> dict:
    return cfg.get("sharing") or {}


def enabled(cfg: dict) -> bool:
    return bool(options(cfg).get("links"))


def allowed_days(cfg: dict) -> list[int]:
    """Las caducidades que se ofrecen (días; 0 = nunca, solo sin máximo)."""
    return offered_days((1, 7, 30, 90, 365), int(options(cfg).get("max_days") or 0))


def can_share(cfg: dict, user, root: dict) -> bool:
    """Si ``user`` puede crear enlaces de algo de ``root``."""
    return enabled(cfg) and "share" in effective_for_root(permissions_for(user, cfg), root)


def create(conn: Connection, cfg: dict, key: bytes | None, user, root: dict, rel: str, *, mode: str = "download",
           days: int | None = None, password: str = "", max_downloads: int | None = None,
           note: str = "") -> tuple[dict, str]:
    """Crea el enlace y devuelve ``(fila, token)``. :class:`LinkError` con el porqué si no se puede."""
    opts = options(cfg)
    if not enabled(cfg):
        raise LinkError(_("Share links are turned off."))
    perms = effective_for_root(permissions_for(user, cfg), root)
    if "share" not in perms:
        raise LinkError(_("You are not allowed to share with links in this folder."))
    try:
        rel, entry = storage.existing_entry(cfg, root, rel)
    except storage.EntryError as exc:
        raise LinkError(exc.message) from exc
    if entry is None:
        raise LinkError(_("That file or folder does not exist."))
    if mode not in MODES:
        raise LinkError(_("Unknown kind of link."))
    if mode == "upload":
        if not entry.is_dir:
            raise LinkError(_("A drop box is for folders."))
        if not opts.get("upload_links"):
            raise LinkError(_("Drop boxes are turned off."))
        if "upload" not in perms:
            raise LinkError(_("You are not allowed to upload to this folder."))
    elif "download" not in perms:
        raise LinkError(_("You are not allowed to download from this folder."))
    top = int(opts.get("max_days") or 0)
    days = int(opts.get("default_days") or 7) if days is None else int(days)
    if days < 0 or (top and (days == 0 or days > top)):
        raise LinkError(ngettext("A link can last at most %(num)s day.", "A link can last at most %(num)s days.",
                                 top))
    password = password or ""
    if opts.get("require_password") and not password:
        raise LinkError(_("A password is required for share links."))
    if password and len(password) < PASSWORD_MIN:
        raise LinkError(_("The password of a link must be at least %(num)s characters long.", num=PASSWORD_MIN))
    if max_downloads is not None and not 1 <= int(max_downloads) <= MAX_DOWNLOADS:
        raise LinkError(_("The download limit must be between 1 and %(num)s.", num=MAX_DOWNLOADS))
    if key is None:
        raise LinkError(_("The secrets key is not available."))
    token = secrets.token_urlsafe(TOKEN_BYTES)
    link_id = repo.create(
        conn, user_id=user["id"], token_hash=sha256_hex(token), token_enc=secretbox.encrypt(key, token),
        root=root["name"], rel=rel, is_dir=entry.is_dir, mode=mode,
        password_hash=generate_password_hash(password) if password else None,
        expires_at=iso_in(days=days) if days else None,
        max_downloads=int(max_downloads) if max_downloads else None, note=(note or "").strip()[:200] or None)
    return dict(repo.get_by_id(conn, link_id)), token


def find(conn: Connection, token: str):
    """El enlace de ``token`` (o None). Por su hash: el token no se guarda en claro."""
    if not token or len(token) > 100:
        return None
    return repo.get_by_hash(conn, sha256_hex(token))


def token_of(link, key: bytes | None) -> str:
    """El token de un enlace, para enseñárselo de nuevo a su dueño (o ``""`` si no se puede descifrar)."""
    try:
        return secretbox.decrypt(key, link["token_enc"])
    except Exception:  # noqa: BLE001 (otra clave tras restaurar una copia de otro servidor…)
        return ""


def state(link, now: datetime | None = None) -> str:
    """``ok``, ``revoked`` (quitado), ``expired`` (caducado), ``used_up`` (sin descargas) o ``deleted`` (ya no
    existe: :func:`history_link`)."""
    if isinstance(link, dict) and link.get("deleted"):
        return "deleted"
    if "revoked_at" in link.keys() and link["revoked_at"]:
        return "revoked"
    now = now or utcnow()
    if link["expires_at"] and datetime.fromisoformat(link["expires_at"]) <= now:
        return "expired"
    if link["max_downloads"] is not None and link["downloads"] >= link["max_downloads"]:
        return "used_up"
    return "ok"


STATE_LABELS = {"ok": _l("Active"), "revoked": _l("Removed"), "expired": _l("Expired"),
                "used_up": _l("No downloads left"), "deleted": _l("Deleted")}
# Lo que se apunta de cada enlace (share_link_events, la página de actividad): un nombre para cada suceso
EVENT_LABELS = {"created": _l("Created"), "opened": _l("Opened"), "password_failed": _l("Wrong password"),
                "unlocked": _l("Right password"), "download": _l("Download"), "zip": _l("Download as ZIP"),
                "upload": _l("Upload"), "refused": _l("Refused"), "revoked": _l("Removed")}
REFUSED_LABELS = {"revoked": _l("it was removed"), "expired": _l("it had expired"),
                  "used_up": _l("no downloads left"), "unavailable": _l("its owner can no longer share it"),
                  "off": _l("share links are turned off"), "locked": _l("too many wrong passwords"),
                  "too_large": _l("the file was too large"), "quota": _l("no space left in the quota")}


def record(conn: Connection, link, event: str, *, path: str | None = None, ip: str | None = None,
           user_agent: str | None = None, detail: str | None = None) -> None:
    """Apunta un suceso del enlace (con la IP y el navegador de quien lo abre). Se conserva aunque el enlace se
    quite o se borre: es su trazabilidad."""
    repo.log_event(conn, link, event, path=path, ip=ip, user_agent=user_agent, detail=detail)


def events(conn: Connection, uid: str) -> list:
    return repo.events(conn, uid)


# Los filtros de las listas: activos (de entrada), caducados (o sin descargas), quitados, borrados (ya no existen:
# solo su historial) y todos (los que existen)
BUCKETS = ("active", "expired", "revoked", "deleted", "all")


def bucket_label(bucket: str, num: int) -> str:
    """El texto de un filtro con su número («3 activos»): en plural, que en castellano concuerda."""
    if bucket == "expired":
        return ngettext("%(num)s expired", "%(num)s expired", num)
    if bucket == "revoked":
        return ngettext("%(num)s removed", "%(num)s removed", num)
    if bucket == "deleted":
        return ngettext("%(num)s deleted", "%(num)s deleted", num)
    if bucket == "all":
        return ngettext("%(num)s in all", "%(num)s in all", num)
    return ngettext("%(num)s active", "%(num)s active", num)


def bucket_of(link_state: str) -> str:
    return {"ok": "active", "expired": "expired", "used_up": "expired", "revoked": "revoked"}[link_state]


def split(rows, show: str, deleted_count: int = 0) -> tuple[list, dict]:
    """Las filas del filtro ``show`` y cuántas hay en cada uno (``deleted``: las que solo tienen historial)."""
    show = show if show in BUCKETS else "active"
    counts = {b: 0 for b in BUCKETS}
    picked = []
    for row in rows:
        bucket = bucket_of(state(row))
        counts[bucket] += 1
        counts["all"] += 1
        if show in (bucket, "all"):
            picked.append(row)
    counts["deleted"] = deleted_count
    return picked, counts


def deleted_history(conn: Connection, owner: str | None = None) -> list:
    return repo.deleted_history(conn, owner)


def history_link(conn: Connection, uid: str) -> dict | None:
    """Un enlace que ya no existe, reconstruido desde su historial (dueño, lo que compartía, cuándo se creó y se
    quitó), para su página de actividad. None si no hay historial."""
    found = repo.events(conn, uid)
    if not found:
        return None
    first = found[-1]
    root, _sep, rel = (first["target"] or ":/").partition(":/")
    created = next((e for e in found if e["event"] == "created"), None)
    revoked = next((e for e in found if e["event"] == "revoked"), None)
    # «created»: «<quién>: <modo>, <días>d, password, max=<n>» (web/views/links.create)
    parts = ((created["detail"] or "") if created else "").split(": ", 1)[-1].split(", ")
    mode = parts[0] if parts[0] in MODE_LABELS else "download"
    reason, _sep, by = ((revoked["detail"] or "") if revoked else "").partition(":")
    return {"uid": uid, "owner": first["owner"], "user_id": None, "root": root, "rel": rel, "mode": mode,
            "password_hash": "password" in parts, "created_at": created["at"] if created else first["at"],
            "expires_at": None, "max_downloads": None, "revoked_at": revoked["at"] if revoked else None,
            "revoked_by": by or None, "revoke_reason": reason or None, "deleted": True}


def activity(conn: Connection, uids: list[str]) -> dict[str, dict]:
    """Visitas, descargas, subidas, rechazos y último acceso de cada enlace."""
    return repo.summary(conn, uids)


def check_password(link, password: str) -> bool:
    return bool(link["password_hash"]) and check_password_hash(link["password_hash"], password or "")


def resolve(conn: Connection, cfg: dict, link) -> tuple[object, dict, frozenset]:
    """Quién lo creó, su carpeta de StorageWeb y sus permisos en ella, AHORA. :class:`LinkError` si el enlace ya no
    puede funcionar (cuenta desactivada, carpeta que ya no tiene, permiso que perdió, enlaces apagados)."""
    if not enabled(cfg):
        raise LinkError(_("Share links are turned off."))
    owner = user_repo.get_by_id(conn, link["user_id"])
    if owner is None or not owner["enabled"]:
        raise LinkError(_("This link is no longer available."))
    try:
        root = storage.find_root(owner, cfg, link["root"])
    except storage.RootNotFound as exc:
        raise LinkError(_("This link is no longer available.")) from exc
    perms = effective_for_root(permissions_for(owner, cfg), root)
    needed = "upload" if link["mode"] == "upload" else "download"
    if "share" not in perms or needed not in perms:
        raise LinkError(_("This link is no longer available."))
    return owner, root, perms


def inside(link, sub: str) -> str:
    """La ruta (en la carpeta de StorageWeb) de ``sub`` dentro de lo compartido. Nunca sale de ello: ``..`` y las
    rutas absolutas las rechaza ``clean_rel``; un enlace a un archivo solo da ese archivo."""
    try:
        sub = backends.clean_rel(sub or "")
    except PathError as exc:
        raise LinkError(_("That path is not valid.")) from exc
    if sub and not link["is_dir"]:
        raise LinkError(_("That path is not valid."))
    return backends.join_rel(link["rel"], sub) if sub else link["rel"]


def for_user(conn: Connection, user) -> list:
    return repo.list_for_user(conn, user["id"])


def all_links(conn: Connection) -> list:
    return repo.list_all(conn)


def get(conn: Connection, uid: str):
    return repo.get_by_uid(conn, uid)


def revoke(conn: Connection, uid: str, actor, *, admin: bool = False, ip: str | None = None,
           user_agent: str | None = None) -> dict | None:
    """Deja de compartir el enlace ``uid``: el de ``actor`` o, con ``admin``, cualquiera. No se borra: queda
    «quitado», con quién y cuándo, y su historial. Lo devuelve, o None si no existe, no es suyo o ya estaba quitado."""
    link = repo.get_by_uid(conn, uid)
    if link is None or link["revoked_at"] or (not admin and link["user_id"] != actor["id"]):
        return None
    reason = "owner" if link["user_id"] == actor["id"] else "admin"
    repo.revoke(conn, link["id"], actor["username"], reason)
    record(conn, link, "revoked", ip=ip, user_agent=user_agent, detail=f"{reason}:{actor['username']}")
    return dict(link)


def moved(conn: Connection, user, root: str, rel: str, new_root: str, new_rel: str) -> None:
    repo.moved(conn, root, rel, new_root, new_rel, storage.home_owner(user, root, new_root))


def deleted(conn: Connection, user, root: str, rel: str) -> None:
    """Se borró lo compartido (o lo que lo contenía): sus enlaces quedan quitados, con su historial."""
    for link in repo.matching(conn, root, rel, storage.home_owner(user, root)):
        repo.revoke(conn, link["id"], user["username"], "deleted")
        record(conn, link, "revoked", detail=f"deleted:{user['username']}")


@maintenance.task("link_cleanup", every=lambda cfg: 24, order=75)
def _purge(conn: Connection, cfg: dict) -> None:
    """Borra las filas de los enlaces quitados o caducados hace más de ``sharing.keep_days`` días (0 = nunca; su
    historial se queda) y el historial más viejo que ``sharing.history_days`` (0 = la retención de la auditoría,
    ``maintenance.audit_retention_days``; 0 también = todo se guarda). Lo que borra queda en la auditoría."""
    sharing = cfg.get("sharing") or {}
    keep = int(sharing.get("keep_days", KEEP_EXPIRED_DAYS) or 0)
    links_removed = repo.purge_old(conn, iso_ago(days=keep)) if keep else 0
    days = int(sharing.get("history_days") or 0) or int(((cfg.get("maintenance") or {}).get("audit_retention_days")) or 0)
    events_removed = repo.purge_events(conn, iso_ago(days=days)) if days else 0
    if links_removed or events_removed:
        from ..db.repositories import audit  # noqa: PLC0415
        audit.log(conn, "links_purged", detail=f"links={links_removed} events={events_removed}")

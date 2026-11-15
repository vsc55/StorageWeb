"""Unidad de red: servidor WebDAV en ``/dav/`` (Windows, macOS, Linux, rclone, Cyberduck…).

``/dav/`` muestra las carpetas del usuario (la personal y las compartidas a las que entra) y
``/dav/<carpeta>/<ruta>`` su contenido, en cualquier almacenamiento (disco, S3, SFTP…).

Seguridad (ver ``guards._load_dav_user``):

- Solo credenciales en la cabecera (``Basic usuario:token`` o ``Bearer token``); la cookie del navegador
  no sirve aquí, así que no hace falta CSRF.
- Los mismos permisos que la web, en cada petición: rol, permisos de la carpeta, solo lectura y alcance
  del token. Sobrescribir un archivo existente exige además el permiso de borrar.
- Rutas y nombres por ``clean_rel``/``safe_filename``: nada sale de la carpeta.
- Los archivos se sirven como adjunto y con ``Content-Security-Policy: sandbox``.

Bloqueos (``LOCK``) simulados: Windows, macOS y Office los piden para escribir, pero no impiden que dos
personas editen a la vez. Clase DAV 1 y 2.
"""
from __future__ import annotations

import mimetypes
import secrets
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, g, request
from werkzeug.exceptions import HTTPException

from ... import patterns
from ... import metrics
from ...core import backends, quota, storage, tokens
from ...core.permissions import effective_for_root, permissions_for
from ...core.security import UPLOAD_TMP_PREFIX, PathError, safe_filename
from ...core.uploads import UploadError, check_space
from ...db.repositories import audit
from ...i18n import _
from ..context import get_db, settings
from ..downloads import SANDBOX, etag, send_entry
from ..guards import client_ip

bp = Blueprint("dav", __name__, url_prefix="/dav")


class InsufficientStorage(HTTPException):
    """507 (RFC 4918): no cabe (cuota o disco). Werkzeug no la trae."""
    code = 507
    name = "Insufficient Storage"
    description = "Not enough space for this request."

METHODS = ["OPTIONS", "PROPFIND", "PROPPATCH", "GET", "HEAD", "PUT", "DELETE", "MKCOL", "COPY", "MOVE", "LOCK",
           "UNLOCK"]
DAV_HEADERS = {"DAV": "1, 2", "MS-Author-Via": "DAV", "Allow": ", ".join(METHODS)}
LOCK_SECONDS = 3600
CHUNK = 1024 * 1024
XML = "application/xml; charset=utf-8"


# --------------------------------------------------------------------------- utilidades

def _xml(body: str, status: int = 207, headers: dict | None = None) -> Response:
    return Response('<?xml version="1.0" encoding="utf-8"?>\n' + body, status=status, mimetype="application/xml",
                    headers={"Content-Type": XML, **(headers or {})})


def _empty(status: int, headers: dict | None = None) -> Response:
    return Response(b"", status=status, headers=headers or {})


def _href(root_name: str = "", rel: str = "", is_dir: bool = False) -> str:
    parts = [p for p in (root_name, *rel.split("/")) if p]
    path = request.script_root + "/dav/" + "/".join(urllib.parse.quote(p) for p in parts)
    return path + ("/" if is_dir and parts else "")


def _split(sub: str) -> tuple[str, str]:
    """``carpeta/ruta/dentro`` → (carpeta, ruta limpia). 404 si la ruta no es segura."""
    try:
        clean = backends.clean_rel(sub)
    except PathError:
        abort(404)
    root_name, _sep, rel = clean.partition("/")
    return root_name, rel


def _root(name: str) -> dict:
    try:
        return storage.find_root(g.user, settings(), name)
    except storage.RootNotFound:
        abort(404)


def _perms(root: dict) -> frozenset[str]:
    return tokens.restrict(effective_for_root(permissions_for(g.user, settings()), root), g.get("api_token"))


def _require(root: dict, *needed: str) -> None:
    if not set(needed) <= _perms(root):
        abort(403)


def _stat(root: dict, rel: str):
    try:
        return root["backend"].stat(rel)
    except backends.BackendError:
        abort(502)


def _audit(action: str, root: dict, rel: str, detail: str = "webdav") -> None:
    audit.log(get_db(), action, f"{root['name']}:/{rel}", username=g.user["username"], ip=client_ip(), detail=detail)


def _etags(header: str) -> set[str]:
    return {t.strip().removeprefix("W/").strip('"') for t in header.split(",") if t.strip()}


def _preconditions(entry) -> None:
    """Escritura condicional (RFC 7232): ``If-Match`` y ``If-None-Match``. 412 si no se cumplen.

    Así un cliente (la extensión de VS Code, rclone…) no pisa un cambio hecho por otro: sube con la
    versión que conoce y, si el archivo cambió en el servidor, recibe 412 en vez de sobrescribirlo.
    """
    current = etag(entry) if entry is not None and not entry.is_dir else None
    if_match = request.headers.get("If-Match")
    if if_match is not None:
        wanted = _etags(if_match)
        if entry is None or ("*" not in wanted and current not in wanted):
            abort(412)
    if_none = request.headers.get("If-None-Match")
    if if_none is not None and entry is not None:
        wanted = _etags(if_none)
        if "*" in wanted or current in wanted:
            abort(412)


def _check_quota(root: dict, incoming: int, freed: int = 0) -> None:
    """507 (Insufficient Storage, RFC 4918) con el motivo si no cabe en la cuota de la carpeta."""
    try:
        quota.check(root, settings(), incoming, freed)
    except quota.QuotaExceeded as exc:
        raise InsufficientStorage(exc.message) from exc


def _check_name(rel: str) -> None:
    """En WebDAV el nombre lo elige el cliente: si no es válido tal cual, se rechaza (no se cambia)."""
    name = backends.name_of(rel)
    try:
        if safe_filename(name) != name:
            abort(400)
    except ValueError:
        abort(400)


# --------------------------------------------------------------------------- autenticación y cabeceras

@bp.before_request
def _authenticate():
    if g.get("user") is None and request.method != "OPTIONS":
        return _empty(401, {"WWW-Authenticate": 'Basic realm="StorageWeb", charset="UTF-8"'})
    return None


@bp.after_app_request
def _dav_on_site_root(response):
    """Windows pregunta ``OPTIONS /`` antes de conectar una unidad: se le dice que hay WebDAV."""
    if request.method == "OPTIONS" and request.path == "/":
        response.headers.update({"DAV": DAV_HEADERS["DAV"], "MS-Author-Via": "DAV"})
    return response


# --------------------------------------------------------------------------- PROPFIND / PROPPATCH

def _requested_props() -> list[tuple[str, str]] | None:
    """Propiedades pedidas en un PROPFIND, o ``None`` = todas (``allprop`` o cuerpo vacío)."""
    body = request.get_data(cache=False)
    if not body.strip():
        return None
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        abort(400)
    try:
        doc = ET.fromstring(body)
    except ET.ParseError:
        abort(400)
    prop = doc.find("{DAV:}prop")
    if prop is None:
        return None
    return [(child.tag[1:].partition("}")[0], child.tag.partition("}")[2]) if child.tag.startswith("{")
            else ("", child.tag) for child in prop]


def _props(name: str, entry_is_dir: bool, size: int = 0, mtime: float = 0.0, entry=None) -> dict[str, str]:
    modified = datetime.fromtimestamp(mtime or 0, timezone.utc)
    props = {
        "displayname": escape(name),
        "resourcetype": "<d:collection/>" if entry_is_dir else "",
        "getlastmodified": format_datetime(modified, usegmt=True),
        "creationdate": modified.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "supportedlock": ("<d:lockentry><d:lockscope><d:exclusive/></d:lockscope><d:locktype><d:write/></d:locktype>"
                          "</d:lockentry><d:lockentry><d:lockscope><d:shared/></d:lockscope><d:locktype><d:write/>"
                          "</d:locktype></d:lockentry>"),
        "lockdiscovery": "",
    }
    if not entry_is_dir:
        props.update(getcontentlength=str(size), getetag=f'"{etag(entry)}"' if entry else "",
                     getcontenttype=mimetypes.guess_type(name)[0] or "application/octet-stream")
    return props


# Cuota de las carpetas (RFC 4331): el Explorador de Windows las pide para mostrar el espacio de la unidad. Solo
# se calculan si se piden expresamente (no van en «allprop»: contar lo que ocupa una carpeta puede costar).
QUOTA_PROPS = ("quota-available-bytes", "quota-used-bytes")


def _wants_quota(wanted: list[tuple[str, str]] | None) -> bool:
    return bool(wanted) and any(ns == "DAV:" and local in QUOTA_PROPS for ns, local in wanted)


def _quota_props(root: dict) -> dict[str, str]:
    """Lo usado y lo que queda: el mínimo entre lo que deja la cuota y el espacio libre del almacenamiento (si
    se sabe). Sin cuota ni espacio conocido, solo lo usado."""
    try:
        used, _complete = quota.usage(root)
        space = root["backend"].space("") or {}
    except (backends.BackendError, OSError):
        return {}
    limit = quota.limit_bytes(root)
    available = max(limit - used, 0) if limit > 0 else None
    if "free" in space:
        available = space["free"] if available is None else min(available, space["free"])
    props = {"quota-used-bytes": str(used)}
    if available is not None:
        props["quota-available-bytes"] = str(available)
    return props


def _response(href: str, props: dict[str, str], wanted: list[tuple[str, str]] | None) -> str:
    if wanted is None:
        found = "".join(f"<d:{k}>{v}</d:{k}>" if v else f"<d:{k}/>" for k, v in props.items())
        missing = ""
    else:
        found = "".join((f"<d:{local}>{props[local]}</d:{local}>" if props[local] else f"<d:{local}/>")
                        for ns, local in wanted if ns == "DAV:" and local in props)
        missing = "".join(f'<x:{escape(local)} xmlns:x="{escape(ns)}"/>' if ns else f"<{escape(local)}/>"
                          for ns, local in wanted if not (ns == "DAV:" and local in props))
    out = f"<d:response><d:href>{escape(href)}</d:href>"
    out += f"<d:propstat><d:prop>{found}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
    if missing:
        out += f"<d:propstat><d:prop>{missing}</d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>"
    return out + "</d:response>"


# Una ruta oculta para todos (storage.hidden) responde como si no existiera (404; 403 al crearla) con esta marca,
# para que un cliente que sincroniza no la borre de su equipo creyendo que se borró ni la reintente sin fin.
# Solo se dice de la ruta que el cliente pide (ya la conoce): la lista de patrones no se envía nunca.
HIDDEN_HEADER = "X-StorageWeb-Hidden"


def _hidden_response(status: int) -> Response:
    return Response(f"{status} {'Not Found' if status == 404 else 'Forbidden'}\n", status=status,
                    mimetype="text/plain", headers={HIDDEN_HEADER: "1"})


def _multistatus(responses: list[str]) -> Response:
    return _xml('<d:multistatus xmlns:d="DAV:">' + "".join(responses) + "</d:multistatus>")


def _depth() -> str:
    depth = request.headers.get("Depth", "infinity").strip().lower()
    return depth if depth in ("0", "1") else "infinity"


def _propfind_top() -> Response:
    """``/dav/``: una colección con las carpetas del usuario."""
    wanted = _requested_props()
    roots = storage.available_roots(g.user, settings())
    quota_of = _quota_props if _wants_quota(wanted) else (lambda _root: {})
    # La raíz de la unidad muestra el espacio de la carpeta personal
    responses = [_response(_href(), {**_props("StorageWeb", True), **quota_of(roots[0])}, wanted)]
    if _depth() != "0":
        for root in roots:
            responses.append(_response(_href(root["name"], is_dir=True),
                                       {**_props(str(root["label"]), True), **quota_of(root)}, wanted))
    return _multistatus(responses)


def _propfind(root: dict, rel: str) -> Response:
    wanted = _requested_props()
    entry = _stat(root, rel)
    if entry is None:
        abort(404)
    name = backends.name_of(rel) or str(root["label"])
    folder_quota = _quota_props(root) if _wants_quota(wanted) else {}  # la de la carpeta, para cada subcarpeta
    responses = [_response(_href(root["name"], rel, entry.is_dir),
                           {**_props(name, entry.is_dir, entry.size, entry.mtime, entry),
                            **(folder_quota if entry.is_dir else {})}, wanted)]
    if entry.is_dir and _depth() == "infinity":
        return _xml('<d:error xmlns:d="DAV:"><d:propfind-finite-depth/></d:error>', 403)
    if entry.is_dir and _depth() == "1":
        try:
            # Siempre con los que empiezan por punto: `storage.show_hidden` es una preferencia de la web, y
            # ocultárselos a un cliente que sincroniza le hace creer que se borraron (y se pueden pedir igual)
            children = storage.list_directory(root, rel, True, hidden=patterns.of(settings()))
        except (backends.BackendError, PermissionError):
            abort(502)
        for child in children:
            child_entry = backends.Entry(child["name"], child["is_dir"], child["bytes"], child["ts"])
            responses.append(_response(_href(root["name"], child["rel"], child["is_dir"]),
                                       {**_props(child["name"], child["is_dir"], child["bytes"], child["ts"],
                                                 child_entry), **(folder_quota if child["is_dir"] else {})},
                                       wanted))
    return _multistatus(responses)


def _proppatch(root: dict, rel: str) -> Response:
    """Windows y macOS fijan fechas y atributos: se responde que sí (StorageWeb no los guarda)."""
    _require(root, "upload")
    if _stat(root, rel) is None:
        abort(404)
    body = request.get_data(cache=False)
    names = []
    if body.strip() and b"<!DOCTYPE" not in body and b"<!ENTITY" not in body:
        try:
            for prop in ET.fromstring(body).iter("{DAV:}prop"):
                names += [child.tag for child in prop]
        except ET.ParseError:
            abort(400)
    props = "".join(f'<x:{escape(t.partition("}")[2])} xmlns:x="{escape(t[1:].partition("}")[0])}"/>'
                    if t.startswith("{") else f"<{escape(t)}/>" for t in names)
    return _multistatus([f"<d:response><d:href>{escape(_href(root['name'], rel))}</d:href><d:propstat>"
                         f"<d:prop>{props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"])


# --------------------------------------------------------------------------- escritura

def _put(root: dict, rel: str) -> Response:
    if not rel:
        abort(405)
    backend = root["backend"]
    entry = _stat(root, rel)
    if entry is not None and entry.is_dir:
        abort(405)
    _require(root, "upload", *(("delete",) if entry is not None else ()))  # sobrescribir = borrar lo anterior
    _preconditions(entry)
    _check_name(rel)
    parent = backends.parent_rel(rel)
    if not backend.is_dir(parent):
        abort(409)
    length = request.content_length
    limit = settings()["storage"]["max_file_size_mb"] * 1024 * 1024
    if limit and length and length > limit:
        abort(413)
    old_size = entry.size if entry is not None else 0  # sobrescribir libera lo anterior
    _check_quota(root, length or 0, old_size)
    try:
        if length:
            check_space(backend, parent, length)
    except UploadError:
        raise InsufficientStorage()
    tmp = backend.staging_dir(parent) / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
    received = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                block = request.stream.read(CHUNK)
                if not block:
                    break
                received += len(block)
                if limit and received > limit:
                    abort(413)
                out.write(block)
        if not length:
            _check_quota(root, received, old_size)  # sin Content-Length: ahora se sabe cuánto es
        backend.store(tmp, rel)
    except backends.BackendError:
        abort(502)
    finally:
        tmp.unlink(missing_ok=True)
    _audit("upload", root, rel, f"webdav:{received}")
    stored = _stat(root, rel)
    quota.record(root, received - old_size)
    metrics.inc("storageweb_upload_bytes_total", received, via="webdav")
    return _empty(204 if entry is not None else 201, {"ETag": f'"{etag(stored)}"'} if stored else None)


def _mkcol(root: dict, rel: str) -> Response:
    _require(root, "mkdir")
    if not rel:
        abort(405)
    if request.get_data(cache=False):
        abort(415)
    if _stat(root, rel) is not None:
        abort(405)
    _check_name(rel)
    if not root["backend"].is_dir(backends.parent_rel(rel)):
        abort(409)
    try:
        root["backend"].mkdir(rel)
    except FileExistsError:
        abort(405)
    except backends.BackendError:
        abort(502)
    _audit("mkdir", root, rel)
    return _empty(201)


def _delete(root: dict, rel: str) -> Response:
    _require(root, "delete")
    if not rel:
        abort(403)  # la raíz de una carpeta no se borra desde aquí
    entry = _stat(root, rel)
    if entry is None:
        abort(404)
    _preconditions(entry)
    try:
        root["backend"].delete(rel)
    except (backends.BackendError, OSError):
        abort(502)
    quota.invalidate(root)
    _audit("delete", root, rel)
    return _empty(204)


def _destination() -> tuple[dict, str]:
    """La cabecera ``Destination``: carpeta y ruta (siempre dentro de ``/dav/`` de este servidor)."""
    target = urllib.parse.urlsplit(request.headers.get("Destination", ""))
    if target.netloc and target.netloc.lower() != request.host.lower():
        abort(502)  # otro servidor: WebDAV no copia entre servidores
    path = urllib.parse.unquote(target.path)
    prefix = request.script_root + "/dav/"
    if not path.startswith(prefix):
        abort(502)  # otra parte de la aplicación
    root_name, rel = _split(path[len(prefix):])
    if not rel:
        abort(403)
    return _root(root_name), rel


def _copy_move(root: dict, rel: str, move: bool) -> Response:
    if not rel:
        abort(403)
    entry = _stat(root, rel)
    if entry is None:
        abort(404)
    _preconditions(entry)
    dst_root, dst_rel = _destination()
    _check_name(dst_rel)
    if storage.is_hidden(settings(), dst_rel):
        return _hidden_response(403)
    same = dst_root["name"] == root["name"]
    if move:
        _require(root, *(("rename",) if same else ("download", "delete")))
    else:
        _require(root, "download")
    if not (move and same):
        _require(dst_root, "upload")
    overwrite = request.headers.get("Overwrite", "T").strip().upper() != "F"
    existing = _stat(dst_root, dst_rel)
    if existing is not None:
        if not overwrite:
            abort(412)
        _require(dst_root, "delete")
    if not dst_root["backend"].is_dir(backends.parent_rel(dst_rel)):
        abort(409)
    if same and (dst_rel == rel or dst_rel.startswith(rel + "/")):
        abort(403)  # en sí misma
    if not (move and same):
        try:
            size = quota.size_of(root["backend"], rel)
            freed = quota.size_of(dst_root["backend"], dst_rel) if existing is not None else 0
        except backends.BackendError:
            abort(502)
        _check_quota(dst_root, size, freed)
    try:
        if existing is not None:
            dst_root["backend"].delete(dst_rel)
        if move and same:
            root["backend"].move(rel, dst_rel)
        else:
            backends.copy_between(root["backend"], rel, dst_root["backend"], dst_rel)
            if move:
                root["backend"].delete(rel)
    except FileExistsError:
        abort(412)
    except FileNotFoundError:
        abort(409)
    except (backends.BackendError, OSError):
        abort(502)
    quota.invalidate(root, dst_root)
    target = f"{dst_root['name']}:/{dst_rel}"
    _audit("rename" if move else "upload", root, rel, f"webdav:{'move' if move else 'copy'}:{target}")
    return _empty(204 if existing is not None else 201)


# --------------------------------------------------------------------------- bloqueos (simulados)

def _lock(root: dict, rel: str) -> Response:
    token = request.headers.get("If", "").strip("()<> ") if not request.get_data(cache=False).strip() else ""
    token = token if token.startswith("opaquelocktoken:") else f"opaquelocktoken:{uuid.uuid4()}"
    status = 200
    if _stat(root, rel) is None:
        # LOCK sobre algo que no existe lo crea vacío (Office y Windows lo hacen antes del PUT)
        _require(root, "upload")
        if not rel:
            abort(409)
        _check_name(rel)
        backend = root["backend"]
        if not backend.is_dir(backends.parent_rel(rel)):
            abort(409)
        tmp = backend.staging_dir(backends.parent_rel(rel)) / f"{UPLOAD_TMP_PREFIX}{secrets.token_hex(8)}.part"
        tmp.write_bytes(b"")
        try:
            backend.store(tmp, rel)
        except backends.BackendError:
            abort(502)
        finally:
            tmp.unlink(missing_ok=True)
        status = 201
    owner = escape(g.user["username"])
    body = ('<d:prop xmlns:d="DAV:"><d:lockdiscovery><d:activelock><d:locktype><d:write/></d:locktype>'
            "<d:lockscope><d:exclusive/></d:lockscope><d:depth>0</d:depth>"
            f"<d:owner>{owner}</d:owner><d:timeout>Second-{LOCK_SECONDS}</d:timeout>"
            f"<d:locktoken><d:href>{escape(token)}</d:href></d:locktoken>"
            f"<d:lockroot><d:href>{escape(_href(root['name'], rel))}</d:href></d:lockroot>"
            "</d:activelock></d:lockdiscovery></d:prop>")
    return _xml(body, status, {"Lock-Token": f"<{token}>"})


# --------------------------------------------------------------------------- reparto

def _options() -> Response:
    return _empty(200, {**DAV_HEADERS, "Content-Length": "0"})


def _folder_page() -> Response:
    text = _("This is a WebDAV folder of StorageWeb: connect it as a network drive or with a WebDAV client.")
    return Response(text, mimetype="text/plain", headers={"Content-Security-Policy": SANDBOX})


def dav(sub: str = ""):
    method = request.method
    if method == "OPTIONS":
        return _options()
    root_name, rel = _split(sub)
    if not root_name:
        if method == "PROPFIND":
            return _propfind_top()
        if method in ("GET", "HEAD"):
            return _folder_page()
        if method in ("LOCK", "UNLOCK", "PROPPATCH"):
            abort(403)
        abort(405)
    if storage.is_hidden(settings(), rel):  # oculto para todos: no existe, y no se puede crear
        return _hidden_response(403 if method in ("PUT", "MKCOL") else 404)
    root = _root(root_name)
    if method == "PROPFIND":
        return _propfind(root, rel)
    if method in ("GET", "HEAD"):
        entry = _stat(root, rel)
        if entry is None:
            abort(404)
        if entry.is_dir:
            return _folder_page()
        _require(root, "download")
        if method == "GET":
            _audit("download", root, rel)
        return send_entry(root, rel, entry, head=method == "HEAD")
    if method == "PUT":
        return _put(root, rel)
    if method == "MKCOL":
        return _mkcol(root, rel)
    if method == "DELETE":
        return _delete(root, rel)
    if method in ("COPY", "MOVE"):
        return _copy_move(root, rel, method == "MOVE")
    if method == "PROPPATCH":
        return _proppatch(root, rel)
    if method == "LOCK":
        return _lock(root, rel)
    if method == "UNLOCK":
        return _empty(204)
    abort(405)


bp.add_url_rule("/", "root", dav, methods=METHODS, provide_automatic_options=False, strict_slashes=False)
bp.add_url_rule("/<path:sub>", "item", dav, methods=METHODS, provide_automatic_options=False)

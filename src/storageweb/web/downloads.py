"""Enviar un archivo de cualquier almacenamiento con soporte de rangos (lo usan el explorador y WebDAV).

En el disco del servidor, ``send_file`` con la ruta. En S3, SMB, SFTP… un fichero remoto con ``seek``
y el tamaño conocido, para que ``Range`` funcione igual (reanudar descargas, vídeo).

Como **adjunto** y con ``Content-Security-Policy: sandbox``: un HTML o un SVG subido por un usuario nunca se
ejecuta en el origen de StorageWeb aunque se abra en el navegador. El visor (``files.inline``) sirve imágenes, PDF,
vídeo y audio **en línea**, pero siempre con el tipo que decide él (``mimetype``), nunca el del archivo.
"""
from __future__ import annotations

import csv
import io
import mimetypes
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import quote

from flask import Response, abort, request, send_file, stream_with_context

from .. import metrics
from ..core import backends
from ..core import files as files_core

SANDBOX = "sandbox"


def send_entry(root: dict, rel: str, entry, *, head: bool = False, mimetype: str | None = None,
               csp: str = SANDBOX):
    """Respuesta con el archivo ``rel`` de ``root`` (``entry`` = su ``Entry``). ``head``: solo cabeceras.

    Con ``mimetype``, en línea (no como adjunto) y con ese tipo; ``csp`` es la política de la respuesta."""
    local = root["backend"].local_path(rel)
    inline = mimetype is not None
    if local is not None:
        rv = send_file(local, as_attachment=not inline, download_name=local.name, conditional=True, max_age=0,
                       etag=etag(entry), mimetype=mimetype)  # la misma versión que publica WebDAV
    else:
        try:
            fh, size, mtime = root["backend"].open(rel)
        except FileNotFoundError:
            abort(404)
        except backends.BackendError as exc:
            abort(502, description=exc.message)
        rv = send_file(fh, as_attachment=not inline, download_name=entry.name, conditional=False, max_age=0,
                       mimetype=mimetype or mimetypes.guess_type(entry.name)[0] or "application/octet-stream")
        rv.content_length = size  # send_file no sabe el tamaño de un fichero que no está en disco
        rv.last_modified = datetime.fromtimestamp(mtime, timezone.utc) if mtime else None
        rv.set_etag(etag(entry))
        rv = rv.make_conditional(request.environ, accept_ranges=True, complete_length=size)
    rv.headers["Content-Security-Policy"] = csp
    if head:
        rv.response = []
    elif rv.status_code in (200, 206):  # un 304 no manda nada
        metrics.inc("storageweb_download_bytes_total", rv.content_length or 0,
                    via="webdav" if request.blueprint == "dav" else "web")
    return rv


def etag(entry) -> str:
    """Identificador de versión: cambia si cambian el tamaño o la fecha (en milisegundos)."""
    return f"{int(entry.mtime * 1000)}-{entry.size}"


def attachment(body, mimetype: str, filename: str) -> Response:
    """Una respuesta para guardar (``attachment``): el nombre en ASCII para los navegadores viejos y en UTF-8
    (RFC 5987) para los demás; aislada (``sandbox``) y sin guardar en cachés. ``body``: texto, bytes o un
    generador."""
    fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in filename)
    rv = Response(body, mimetype=mimetype)
    rv.headers["Content-Disposition"] = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
    rv.headers["Content-Security-Policy"] = SANDBOX
    rv.headers["Cache-Control"] = "no-store"
    return rv


def zip_response(cfg: dict, items: list[tuple[dict, str]]) -> Response:
    """Carpetas y archivos (``(raíz, ruta)``) como un ZIP que se va generando mientras se descarga."""
    return attachment(stream_with_context(files_core.zip_stream(cfg, items)), "application/zip",
                      files_core.zip_name(items))


def csv_response(header: list[str], rows: Iterable[list], filename: str) -> Response:
    """Una tabla en CSV para descargar, con BOM para que Excel respete los acentos."""
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return attachment(out.getvalue(), "text/csv; charset=utf-8", filename)


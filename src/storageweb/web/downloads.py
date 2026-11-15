"""Enviar un archivo de cualquier almacenamiento con soporte de rangos (lo usan el explorador y WebDAV).

En el disco del servidor, ``send_file`` con la ruta. En S3, SMB, SFTP… un fichero remoto con ``seek``
y el tamaño conocido, para que ``Range`` funcione igual (reanudar descargas, vídeo).

Siempre como **adjunto** y con ``Content-Security-Policy: sandbox``: un HTML o un SVG subido por un
usuario nunca se ejecuta en el origen de StorageWeb aunque se abra en el navegador.
"""
from __future__ import annotations

import mimetypes
from datetime import datetime, timezone

from flask import abort, request, send_file

from .. import metrics
from ..core import backends

SANDBOX = "sandbox"


def send_entry(root: dict, rel: str, entry, *, head: bool = False):
    """Respuesta con el archivo ``rel`` de ``root`` (``entry`` = su ``Entry``). ``head``: solo cabeceras."""
    local = root["backend"].local_path(rel)
    if local is not None:
        rv = send_file(local, as_attachment=True, download_name=local.name, conditional=True, max_age=0,
                       etag=etag(entry))  # la misma versión que publica WebDAV
    else:
        try:
            fh, size, mtime = root["backend"].open(rel)
        except FileNotFoundError:
            abort(404)
        except backends.BackendError as exc:
            abort(502, description=exc.message)
        rv = send_file(fh, as_attachment=True, download_name=entry.name, conditional=False, max_age=0,
                       mimetype=mimetypes.guess_type(entry.name)[0] or "application/octet-stream")
        rv.content_length = size  # send_file no sabe el tamaño de un fichero que no está en disco
        rv.last_modified = datetime.fromtimestamp(mtime, timezone.utc) if mtime else None
        rv.set_etag(etag(entry))
        rv = rv.make_conditional(request.environ, accept_ranges=True, complete_length=size)
    rv.headers["Content-Security-Policy"] = SANDBOX
    if head:
        rv.response = []
    elif rv.status_code in (200, 206):  # un 304 no manda nada
        metrics.inc("storageweb_download_bytes_total", rv.content_length or 0,
                    via="webdav" if request.blueprint == "dav" else "web")
    return rv


def etag(entry) -> str:
    """Identificador de versión: cambia si cambian el tamaño o la fecha (en milisegundos)."""
    return f"{int(entry.mtime * 1000)}-{entry.size}"

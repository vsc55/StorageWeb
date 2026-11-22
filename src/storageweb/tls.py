"""Conexiones TLS de StorageWeb como cliente (syslog por TLS, FTPS, WebDAV): un sitio para decidir cómo se comprueba
el certificado. Sin dependencias."""
from __future__ import annotations

import ssl


def client_context(verify: bool = True, cafile: str | None = None) -> ssl.SSLContext:
    """El contexto de siempre (``ssl.create_default_context``) con ``cafile`` como CA propia; con ``verify=False``
    acepta cualquier certificado (servidores internos con uno autofirmado: lo elige el administrador)."""
    context = ssl.create_default_context(cafile=cafile or None)
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context

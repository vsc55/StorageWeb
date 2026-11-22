r"""Las carpetas del disco del servidor que se pueden usar (``storage.allowed_folders``): las carpetas compartidas y
personales que están en el disco (sin ubicación), y lo que enseña el selector de rutas en él. Vacío = cualquiera.

Se compara la ruta **real** (``os.path.realpath``: sin ``..`` y siguiendo los enlaces simbólicos, también los de una
carpeta que aún no existe, hasta donde exista), así que ``D:\Datos\enlace`` que apunta a ``C:\Windows`` está fuera de
``D:\Datos``. En Windows, sin distinguir mayúsculas. Las rutas de red (:func:`network_path`) no se resuelven nunca
(resolverlas es conectarse a ese equipo): se comparan tal cual se escriben.

Sin dependencias del resto de StorageWeb: lo usan ``settings.loader`` (al guardar), ``core.storage`` (al abrir una
carpeta) y ``core.pathpicker`` (al listar).
"""
from __future__ import annotations

import os

_SEPARATORS = (os.sep, os.altsep) if os.altsep else (os.sep,)


def network_path(text: str) -> bool:
    r"""Si es una ruta de red o de dispositivo (``\\equipo\recurso``, ``//equipo/x``, ``\\?\``, ``\\.\``).
    Listarla haría que el SERVIDOR se conectara a ese equipo (en Windows, por SMB: con la cuenta del servicio, cuyo
    hash NTLM se le entrega a quien lo reciba) o abriera un dispositivo."""
    value = str(text or "").strip()
    return value.startswith(("\\\\", "//", "\\/", "/\\"))


def real(path: str) -> str:
    r"""La ruta con la que se compara: real (enlaces resueltos) y, en Windows, en minúsculas. Las de red, solo
    normalizadas: nunca se tocan. Fuera de Windows, con ``/`` en lugar de ``\`` (allí ``\`` no separa carpetas y
    ``\\nas\logs\x`` no estaría dentro de ``\\nas\logs``)."""
    value = os.path.expanduser(str(path))
    if network_path(value):
        if os.sep == "/":
            value = value.replace("\\", "/")
        return os.path.normcase(os.path.normpath(value))
    return os.path.normcase(os.path.realpath(value))


def _under(path: str, base: str) -> bool:
    if path == base:
        return True
    prefix = base if base.endswith(_SEPARATORS) else base + os.sep
    return path.startswith(prefix)


def base_of(path: str, allowed: list[str]) -> str | None:
    """La carpeta permitida que contiene ``path`` (tal como está en el ajuste), o None si ninguna."""
    target = real(path)
    for base in allowed:
        if _under(target, real(base)):
            return base
    return None


def allowed_path(path: str, allowed: list[str]) -> bool:
    """Si ``path`` está dentro de las permitidas: sin lista, cualquiera; con ella, dentro de alguna."""
    return not allowed or base_of(path, allowed) is not None


def permitted(path: str, allowed: list[str]) -> bool:
    r"""Si el servidor puede usar ``path`` como carpeta (o fichero) suya: :func:`allowed_path` y, además, una ruta de
    red (``\\equipo\recurso``) SOLO si está dentro de una carpeta permitida, aunque no haya lista: usarla es
    conectarse a ese equipo con la cuenta del servicio (en Windows, entregándole su hash NTLM). Para un NAS, mejor
    una ubicación de tipo SMB."""
    if network_path(path):
        return bool(allowed) and base_of(path, allowed) is not None
    return allowed_path(path, allowed)

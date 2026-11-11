"""Autenticación contra usuarios del sistema operativo mediante PAM (Linux/macOS)."""
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)


def available() -> bool:
    if sys.platform == "win32":
        return False
    try:
        import pam  # noqa: F401  (python-pam)
    except ImportError:
        return False
    return True


def authenticate(pcfg: dict, username: str, password: str) -> list[str] | None:
    """Devuelve los grupos del SO (en minúsculas) si las credenciales son válidas."""
    if not pcfg.get("enabled") or sys.platform == "win32":
        return None
    try:
        import grp
        import pwd

        import pam
    except ImportError:
        log.error("auth.pam activado pero falta el paquete python-pam")
        return None
    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        return None
    if not pam.pam().authenticate(username, password, service=pcfg.get("service", "login")):
        return None
    groups = {grp.getgrgid(pw.pw_gid).gr_name}
    groups.update(gr.gr_name for gr in grp.getgrall() if username in gr.gr_mem)
    groups = sorted(g.lower() for g in groups)
    allowed = set(pcfg.get("allowed_groups") or [])
    if allowed and not allowed.intersection(groups):
        log.warning("Usuario PAM %s no pertenece a allowed_groups", username)
        return None
    return groups


def system_home(username: str) -> str | None:
    if sys.platform == "win32":
        return None
    import pwd

    try:
        return pwd.getpwnam(username).pw_dir
    except KeyError:
        return None

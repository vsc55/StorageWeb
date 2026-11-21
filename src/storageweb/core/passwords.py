"""La lista de contraseñas comunes que rechaza ``security.password_check``: la que viene con StorageWeb
(``providers/local/common_passwords.txt``) o una propia en ``<data_dir>/common_passwords.txt``, descargada de las
direcciones de ``security.password_list_urls`` (de serie, SecLists) o subida a mano (*Seguridad → Contraseñas* o
``storageweb-admin password-list``). Si existe la propia, manda; *Volver a la de serie* la borra.

Como la de serie: una por línea, en minúsculas, sin repetir y solo las que llegan a la longitud mínima que se puede
pedir (``MIN_PASSWORD_LENGTH``: las más cortas ya las rechaza la longitud). Lo descargado son solo palabras (nunca
se ejecuta nada), con un tope de tamaño y solo por HTTPS. Sin Flask.
"""
from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from ..i18n import _
from ..providers import local

FILE_NAME = "common_passwords.txt"
MAX_BYTES = 64 * 1024 * 1024          # entre todas las fuentes: la de SecLists con un millón son unos 8 MB
TIMEOUT = 60


class PasswordListError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def own_path(data_dir: str | os.PathLike) -> Path:
    return Path(data_dir) / FILE_NAME


def _header(path: Path) -> dict:
    """Los comentarios ``# clave: valor`` del principio de la lista propia."""
    info = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            key, sep, value = line[1:].partition(":")
            if sep:
                info[key.strip()] = value.strip()
    return info


def status(data_dir: str | os.PathLike) -> dict:
    """Qué lista se usa: ``{"own", "count", "source", "updated_at", "sha256"}``."""
    path = own_path(data_dir)
    own = path.is_file()
    used = path if own else local.COMMON_PASSWORDS_FILE
    data = used.read_bytes()
    info = _header(used) if own else {}
    return {"own": own, "count": len(local.common_passwords(str(used))),
            "source": info.get("source", "") if own else "SecLists",
            "updated_at": info.get("updated", "") if own else "",
            "sha256": hashlib.sha256(data).hexdigest()}


def _words(texts: Iterable[str]) -> list[str]:
    found: set[str] = set()
    for text in texts:
        for line in text.splitlines():
            word = line.strip().lower()
            if word.startswith("#") or "�" in word or len(word) < local.MIN_PASSWORD_LENGTH:
                continue
            found.add(word)
    return sorted(found)


def install(data_dir: str | os.PathLike, texts: Iterable[str], source: str) -> int:
    """Guarda la lista propia (escritura atómica) y devuelve cuántas tiene. Vacía: error, no se cambia nada."""
    words = _words(texts)
    if not words:
        raise PasswordListError(_("The list has no password of %(num)s characters or more: nothing was changed.",
                                  num=local.MIN_PASSWORD_LENGTH))
    path = own_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    source = " ".join(str(source).split())[:500]
    body = (f"# Contraseñas comunes que rechaza security.password_check (lista propia de este servidor).\n"
            f"# source: {source}\n# updated: {now}\n" + "\n".join(words) + "\n")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    return len(words)


def _download(url: str, budget: int) -> bytes:
    if not url.lower().startswith("https://"):
        raise PasswordListError(_("Only https:// addresses: %(url)s", url=url))
    request = urllib.request.Request(url, headers={"User-Agent": "StorageWeb"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:  # noqa: S310 (solo https, lo comprueba arriba)
            data = resp.read(budget + 1)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise PasswordListError(_("%(url)s could not be downloaded: %(error)s", url=url,
                                  error=getattr(exc, "reason", None) or exc)) from exc
    if len(data) > budget:
        raise PasswordListError(_("The lists are larger than %(mb)s MB: nothing was changed.",
                                  mb=MAX_BYTES // (1024 * 1024)))
    return data


def download(data_dir: str | os.PathLike, urls: list[str]) -> int:
    """Descarga y junta las listas de ``urls`` (``security.password_list_urls``) como lista propia."""
    urls = [u.strip() for u in urls if u and u.strip()]
    if not urls:
        raise PasswordListError(_("There is no address to download the list from."))
    texts, budget = [], MAX_BYTES
    for url in urls:
        data = _download(url, budget)
        budget -= len(data)
        texts.append(data.decode("utf-8", errors="replace"))
    return install(data_dir, texts, " ".join(urls))


def upload(data_dir: str | os.PathLike, data: bytes, name: str) -> int:
    """Una lista subida a mano (un .txt, una por línea)."""
    if len(data) > MAX_BYTES:
        raise PasswordListError(_("The lists are larger than %(mb)s MB: nothing was changed.",
                                  mb=MAX_BYTES // (1024 * 1024)))
    return install(data_dir, [data.decode("utf-8", errors="replace")], _("file %(name)s", name=name or "?"))


def reset(data_dir: str | os.PathLike) -> bool:
    """Borra la lista propia: vuelve la de serie. False si no había."""
    path = own_path(data_dir)
    if not path.is_file():
        return False
    path.unlink()
    return True

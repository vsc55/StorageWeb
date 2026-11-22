"""Contraseñas de usuarios locales (hash scrypt/pbkdf2 de Werkzeug) y las reglas para ponerlas."""
from __future__ import annotations

import functools
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from ...i18n import _, _l, ngettext

MIN_PASSWORD_LENGTH = 10       # el mínimo de security.password_min_length (y su valor de serie): nunca menos
MAX_PASSWORD_LENGTH = 128      # el máximo que se puede pedir
MIN_DISTINCT_CHARACTERS = 4     # «aaaaaaaaaa», «abababababab»: largas, pero se adivinan enseguida
# Las más comunes de las filtraciones (tools/common_passwords.py): solo las de MIN_PASSWORD_LENGTH o más, en minúsculas
COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")

# Hash ficticio para igualar tiempos cuando el usuario no existe o no tiene contraseña
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


@functools.lru_cache(maxsize=4)
def _read_list(path: str, _stamp: tuple) -> frozenset[str]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def common_passwords(path: str | None = None) -> frozenset[str]:
    """La lista (la de serie o, con ``path``, otra: la propia de ``core/passwords``), leída la primera vez que hace
    falta y otra vez si cambia el fichero (unas 19 000 la de serie, en memoria del proceso)."""
    file = Path(path) if path else COMMON_PASSWORDS_FILE
    try:
        info = file.stat()
    except OSError:
        file, info = COMMON_PASSWORDS_FILE, COMMON_PASSWORDS_FILE.stat()   # la propia se borró: la de serie
    # También el id del fichero: la lista se instala en uno nuevo (fsutil.atomic_write) y en Windows dos seguidas
    # pueden tener la misma fecha y el mismo tamaño
    return _read_list(str(file), (info.st_mtime_ns, info.st_size, info.st_ino))


def rules(cfg: dict) -> dict:
    """Las reglas de los ajustes (``security.password_*``), para :func:`validate_password` / :func:`hash_password`
    (``**local.rules(cfg)``). La lista de comunes: la propia de ``<data_dir>`` si existe."""
    sec = cfg["security"]
    own = Path(cfg["data_dir"]) / "common_passwords.txt" if cfg.get("data_dir") else None
    return {"min_length": int(sec.get("password_min_length") or MIN_PASSWORD_LENGTH),
            "check_common": bool(sec.get("password_check", True)),
            "min_distinct": int(sec.get("password_min_distinct", MIN_DISTINCT_CHARACTERS)),
            "require": tuple(sec.get("password_require") or ()),
            "reject_username": bool(sec.get("password_reject_username", True)),
            "blocklist": tuple(sec.get("password_blocklist") or ()),
            "breach_check": bool(sec.get("password_breach_check", False)),
            "common_file": str(own) if own and own.is_file() else ""}


def _kind(char: str) -> str:
    if char.islower():
        return "lower"
    if char.isupper():
        return "upper"
    if char.isdigit():
        return "digit"
    return "symbol"


KIND_LABELS = {"lower": _l("a lower case letter"), "upper": _l("an upper case letter"), "digit": _l("a digit"),
               "symbol": _l("a symbol (neither a letter nor a digit)")}


def describe(rules_: dict) -> str:
    """Lo que se pide, para quien la escribe: «Al menos 12 caracteres, con una mayúscula y un número.»"""
    text = _("At least %(num)s characters", num=max(int(rules_.get("min_length") or 0), MIN_PASSWORD_LENGTH))
    kinds = [str(KIND_LABELS[k]) for k in rules_.get("require") or () if k in KIND_LABELS]
    if kinds:
        return _("%(rule)s, with %(kinds)s.", rule=text, kinds=", ".join(kinds))
    return text + "."


def checks(password: str, *, username: str = "", min_length: int = MIN_PASSWORD_LENGTH,
           check_common: bool = True, min_distinct: int = MIN_DISTINCT_CHARACTERS, require: tuple | list = (),
           reject_username: bool = True, blocklist: tuple | list = (), breach_check: bool = False,
           common_file: str = ""):
    """Cada regla activa (``security.password_*``, :func:`rules`), de la más barata a la más cara: genera
    ``{"key", "label", "ok", "message"}`` con ``ok`` True, False o None (no se pudo comprobar: las filtraciones sin
    servicio) y, si falla, ``message`` (el porqué, para quien la escribe). Es perezoso: :func:`validate_password` se
    para en la primera que falla (y solo pregunta a internet si todas las demás pasan); el probador de *Seguridad →
    Contraseñas* las recorre todas."""
    def item(key, label, failure):
        return {"key": key, "label": str(label), "ok": failure is None, "message": failure or ""}

    password = password or ""
    min_length = max(int(min_length or 0), MIN_PASSWORD_LENGTH)
    yield item("length", _("At least %(num)s characters", num=min_length),
               _("The password must be at least %(num)s characters long", num=min_length)
               if len(password) < min_length else None)
    if require:
        present = {_kind(c) for c in password}
        wanted = [k for k in require if k in KIND_LABELS]
        missing = [str(KIND_LABELS[k]) for k in wanted if k not in present]
        yield item("require", _("With %(kinds)s", kinds=", ".join(str(KIND_LABELS[k]) for k in wanted)),
                   _("The password must also contain %(kinds)s.", kinds=", ".join(missing)) if missing else None)
    low = password.lower()
    distinct = max(int(min_distinct or 1), 1)
    if distinct > 1:
        yield item("distinct", _("At least %(num)s different characters", num=distinct),
                   _("The password repeats too few characters: it is easy to guess.")
                   if len(set(low)) < distinct else None)
    name = (username or "").strip().lower()
    if reject_username and name:
        yield item("username", _("Does not contain the user name"),
                   _("The password cannot contain your user name.")
                   if low == name or (len(name) >= 4 and name in low) else None)
    if blocklist:
        found = next((w for w in blocklist if w and w.lower() in low), None)
        yield item("blocklist", _("Does not contain forbidden words"),
                   _("The password contains «%(word)s», which is not allowed here: choose another.", word=found)
                   if found else None)
    if check_common:
        yield item("common", _("Is not one of the common passwords"),
                   _("That password is one of the most common ones: choose another.")
                   if low in common_passwords(common_file or None) else None)
    if breach_check:
        from . import breach  # noqa: PLC0415 (solo si está activado)
        times = breach.times_breached(password)
        result = item("breach", _("Does not appear in known data breaches"),
                      ngettext("That password appears in %(num)s known data breach: choose another.",
                               "That password appears in %(num)s known data breaches: choose another.", times)
                      if times else None)
        if times is None:
            result.update(ok=None, message=_("Have I Been Pwned did not answer: it is accepted without this check."))
        yield result


def validate_password(password: str, *, username: str = "", **rules_) -> None:
    """Lanza ``ValueError`` (con el porqué, para quien la escribe) si la contraseña no cumple alguna regla
    (:func:`checks`, con las de :func:`rules`). Sin reglas, las de serie."""
    for result in checks(password, username=username, **rules_):
        if result["ok"] is False:
            raise ValueError(result["message"])


def hash_password(password: str, *, username: str = "", **rules_) -> str:
    """Valida (:func:`validate_password`, con las reglas de :func:`rules`) y devuelve el hash."""
    validate_password(password, username=username, **rules_)
    return generate_password_hash(password)


def verify(password_hash: str | None, password: str) -> bool:
    ok = check_password_hash(password_hash or _DUMMY_HASH, password)
    return ok and bool(password_hash)


def burn_time(password: str) -> None:
    """Consume el mismo tiempo que una verificación real."""
    check_password_hash(_DUMMY_HASH, password)

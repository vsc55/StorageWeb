"""*Seguridad → Estado de la seguridad*: lo que StorageWeb ya sabe de sí mismo, repasado como una lista de
comprobación. Sin Flask y sin red: lee los ajustes efectivos, la base de datos, el estado del mantenimiento (las
copias, la última comprobación de vulnerabilidades de ``core.advisories``) y el diagnóstico de red de la petición.

Cada comprobación dice ``state`` (``ok``, ``warn``, ``bad`` o ``info``: un dato, no un juicio), una frase con el
porqué y la página donde se cambia (``page``, una clave de ``web/nav.py``). Nada aquí opina más allá de lo que se
puede sostener: lo que depende de la organización (si hace falta un SIEM, si la unidad de red se usa) es ``info``.

Las comprobaciones se registran con :func:`check` (como los avisos del Resumen): una nueva es una función más.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from .. import providers
from ..db.repositories import api_tokens, mfa as mfa_repo, users
from ..i18n import _, ngettext
from . import advisories

STATES = ("bad", "warn", "ok", "info")      # también el orden en la página: lo grave, arriba


@dataclass(frozen=True)
class Context:
    """``cfg`` los ajustes efectivos, ``boot`` los de arranque, ``state`` el de mantenimiento, ``network`` el
    diagnóstico de red de la petición (``core.network.diagnose``) y ``secrets_key`` si hay clave de los secretos."""
    conn: Connection
    cfg: dict
    boot: dict
    state: dict
    network: dict
    secrets_key: bool


_CHECKS: list[tuple[int, Callable[[Context], dict | None]]] = []


def check(order: int):
    def decorate(fn):
        _CHECKS.append((order, fn))
        _CHECKS.sort(key=lambda item: item[0])
        return fn
    return decorate


def result(key: str, state: str, title: str, detail: str, page: str, anchor: str = "") -> dict:
    if state not in STATES:
        raise ValueError(state)
    return {"key": key, "state": state, "title": title, "detail": detail, "page": page, "anchor": anchor}


def collect(ctx: Context) -> list[dict]:
    """Todas las comprobaciones, de la más grave a la menos (una que falle no se lleva las demás)."""
    out = []
    for _order, fn in _CHECKS:
        try:
            got = fn(ctx)
        except Exception:  # noqa: BLE001 (la página de estado no puede romperse por una comprobación)
            continue
        if got:
            out.append(got)
    return sorted(out, key=lambda r: STATES.index(r["state"]))


def summary(rows: list[dict]) -> dict:
    """Cuántas de cada estado (para la cabecera de la página)."""
    return {state: sum(1 for r in rows if r["state"] == state) for state in STATES}


# --------------------------------------------------------------------------- las comprobaciones

@check(10)
def _https(ctx: Context) -> dict:
    public = str(ctx.cfg["network"].get("public_url") or "")
    problems = [text for level, text in ctx.network.get("notes", []) if level in ("warn", "danger")]
    if problems:
        return result("https", "bad" if any(level == "danger" for level, _t in ctx.network.get("notes", []))
                      else "warn", _("HTTPS and the public address"), problems[0], "network")
    if not public.startswith("https://"):
        return result("https", "warn", _("HTTPS and the public address"),
                      _("There is no public HTTPS address: passwords and sessions may travel in clear, and passkeys "
                        "are not available."), "network")
    if not ctx.boot["session"].get("cookie_secure"):
        return result("https", "warn", _("HTTPS and the public address"),
                      _("The session cookie is not marked Secure (session.cookie_secure in config.json)."), "network")
    return result("https", "ok", _("HTTPS and the public address"),
                  _("Served at %(url)s with a Secure session cookie.", url=public), "network")


def enrolled_ids(conn: Connection) -> set[int]:
    """Las cuentas con la verificación en dos pasos activa (app o passkey)."""
    return mfa_repo.enrolled_ids(conn)


def password_accounts(conn: Connection) -> list:
    """Las cuentas activas que entran con contraseña (las que pueden tener la verificación en dos pasos)."""
    out = []
    for user in users.list_all(conn):
        method = providers.get(user["source"])
        if user["enabled"] and method is not None and method.password and not method.sso:
            out.append(user)
    return out


@check(20)
def _admins_mfa(ctx: Context) -> dict | None:
    accounts = password_accounts(ctx.conn)
    admins = [u for u in accounts if u["role"] == "admin"]
    if not admins:
        return None             # todos los administradores entran con Entra ID: su MFA es el de Microsoft
    enrolled = mfa_repo.enrolled_ids(ctx.conn)
    missing = [u["username"] for u in admins if u["id"] not in enrolled]
    if not missing:
        return result("admins_mfa", "ok", _("Two-step verification of the administrators"),
                      ngettext("The %(num)s administrator with a password has it.",
                               "All %(num)s administrators with a password have it.", len(admins)), "auth")
    forced = ctx.cfg["security"]["mfa_required"] in ("admins", "all")
    detail = ngettext("%(num)s administrator without it: %(names)s.", "%(num)s administrators without it: %(names)s.",
                      len(missing), names=", ".join(missing[:5]) + ("…" if len(missing) > 5 else ""))
    if forced:
        detail += " " + _("The policy will ask them to set it up on their next sign-in.")
    else:
        detail += " " + _("Require it for administrators in Sign-in.")
    return result("admins_mfa", "warn" if forced else "bad", _("Two-step verification of the administrators"),
                  detail, "auth")


@check(25)
def _users_mfa(ctx: Context) -> dict | None:
    accounts = password_accounts(ctx.conn)
    if not accounts:
        return None
    enrolled = mfa_repo.enrolled_ids(ctx.conn)
    have = sum(1 for u in accounts if u["id"] in enrolled)
    policy = ctx.cfg["security"]["mfa_required"]
    detail = ngettext("%(have)s of %(num)s account with a password has it.",
                      "%(have)s of %(num)s accounts with a password have it.", len(accounts), have=have)
    state = "ok" if policy == "all" or have == len(accounts) else "info"
    if policy != "all":
        detail += " " + _("It is optional for users (policy: %(policy)s).", policy=policy)
    return result("users_mfa", state, _("Two-step verification of the users"), detail, "auth")


@check(30)
def _passwords(ctx: Context) -> dict:
    sec = ctx.cfg["security"]
    if not sec.get("password_check", True):
        return result("passwords", "warn", _("Password rules"),
                      _("Common passwords are accepted. Turn on «Reject common passwords»."), "passwords")
    extra = [_("forbidden words")] if sec.get("password_blocklist") else []
    if sec.get("password_breach_check"):
        extra.append(_("known data breaches"))
    detail = _("At least %(num)s characters; common ones are refused.", num=sec.get("password_min_length", 10))
    if extra:
        detail += " " + _("Also: %(checks)s.", checks=", ".join(extra))
    return result("passwords", "ok", _("Password rules"), detail, "passwords")


@check(40)
def _guessing(ctx: Context) -> dict:
    sec = ctx.cfg["security"]
    if not sec.get("ipban_enabled"):
        return result("guessing", "warn", _("Protection against password guessing"),
                      _("Automatic IP blocking is off: only the per-account lockout slows down an attack."),
                      "security")
    return result("guessing", "ok", _("Protection against password guessing"),
                  _("Locked after %(fails)s failures for %(minutes)s minutes; an address with %(offenses)s offenses "
                    "is blocked.", fails=sec["max_login_failures"], minutes=sec["lockout_minutes"],
                    offenses=sec["ipban_threshold"]), "security")


@check(50)
def _tokens(ctx: Context) -> dict | None:
    sec = ctx.cfg["security"]
    if not sec.get("api_tokens"):
        return result("tokens", "ok", _("API tokens"), _("Turned off."), "clients")
    now = datetime.now(timezone.utc)
    days = int(sec.get("api_token_unused_days") or 0)
    unused = api_tokens.unused_since(ctx.conn, (now - timedelta(days=days)).isoformat(timespec="seconds"),
                                     now.isoformat(timespec="seconds")) if days else 0
    if unused:
        return result("tokens", "warn", _("API tokens"),
                      ngettext("%(num)s valid token unused for more than %(days)s days: better revoke it.",
                               "%(num)s valid tokens unused for more than %(days)s days: better revoke them.",
                               unused, days=days), "sessions")
    if not sec.get("api_token_max_days"):
        return result("tokens", "info", _("API tokens"),
                      _("They can be created without expiry. A longest lifetime limits what a leaked one is worth."),
                      "clients")
    return result("tokens", "ok", _("API tokens"),
                  _("They last %(num)s days at most.", num=sec["api_token_max_days"]), "clients")


@check(55)
def _webdav(ctx: Context) -> dict | None:
    sec = ctx.cfg["security"]
    if not sec.get("webdav"):
        return None
    if sec.get("webdav_passwords"):
        return result("webdav", "warn", _("Network drive"),
                      _("It accepts the account password (saved by Windows, macOS or rclone, and without two-step "
                        "verification). Better API tokens only."), "clients")
    return result("webdav", "ok", _("Network drive"), _("Only with API tokens."), "clients")


@check(60)
def _backups(ctx: Context) -> dict:
    maint = ctx.cfg["maintenance"]
    hours = maint.get("backup_interval_hours") or 0
    if not hours:
        return result("backups", "warn", _("Backups"),
                      _("There are no automatic backups: a broken disk or a mistake has no way back."),
                      "auto_backups")
    last = str(ctx.state.get("backup") or "")
    offsite = (ctx.state.get("offsite") or {}) if maint.get("offsite_location") else None
    if offsite is not None and offsite and not offsite.get("ok"):
        return result("backups", "bad", _("Backups"),
                      _("The last copy outside the server failed: %(error)s", error=offsite.get("error") or "?"),
                      "auto_backups")
    if last and last < (datetime.now(timezone.utc) - timedelta(hours=hours * 2)).isoformat(timespec="seconds"):
        return result("backups", "warn", _("Backups"),
                      _("The last automatic backup is older than expected (%(date)s).", date=last[:16].replace("T", " ")),
                      "auto_backups")
    if offsite is None:
        return result("backups", "info", _("Backups"),
                      _("Every %(num)s hours, only on this server: a copy outside it survives losing the server.",
                        num=hours), "auto_backups")
    return result("backups", "ok", _("Backups"), _("Every %(num)s hours, also outside the server.", num=hours),
                  "auto_backups")


@check(70)
def _audit(ctx: Context) -> dict:
    audit_cfg = ctx.cfg["audit"]
    forwarded = bool(audit_cfg.get("syslog") or audit_cfg.get("file"))
    if forwarded:
        return result("audit", "ok", _("Audit log"),
                      _("It is also sent outside the server (SIEM or file): nobody can erase it from here."),
                      "audit_settings")
    return result("audit", "info", _("Audit log"),
                  _("It is only in this server's database. Sending it to a SIEM keeps it out of reach of whoever "
                    "gets into the server."), "audit_settings")


@check(80)
def _secrets(ctx: Context) -> dict:
    if ctx.secrets_key:
        return result("secrets", "ok", _("Secrets in the settings"),
                      _("Encrypted with the secrets key (AES-256-GCM)."), "system")
    return result("secrets", "bad", _("Secrets in the settings"),
                  _("There is no secrets key: the secrets saved from the web cannot be encrypted."), "system")


@check(90)
def _libraries(ctx: Context) -> dict:
    last = ctx.state.get(advisories.STATE_KEY) or {}
    hours = int(ctx.cfg["security"].get("dependency_check_hours") or 0)
    auto = (_("Checked automatically every %(num)s hours.", num=hours) if hours
            else _("Not checked automatically."))
    if not last:
        return result("libraries", "warn", _("Vulnerabilities in the libraries"),
                      _("Never checked.") + " " + auto, "vulnerabilities", "advisories")
    when = str(last.get("at") or "")[:10]
    if not last.get("vulns_ok"):
        return result("libraries", "warn", _("Vulnerabilities in the libraries"),
                      _("The last check (%(date)s) could not ask the vulnerability database.", date=when) + " " + auto,
                      "vulnerabilities", "advisories")
    total = int(last.get("vuln_total") or 0)
    if total:
        return result("libraries", "bad" if last.get("worst") in ("high", "critical") else "warn",
                      _("Vulnerabilities in the libraries"),
                      ngettext("%(num)s known vulnerability on %(date)s. Update those libraries.",
                               "%(num)s known vulnerabilities on %(date)s. Update those libraries.", total,
                               date=when) + " " + auto, "vulnerabilities", "advisories")
    stale = when < (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    return result("libraries", "warn" if stale and not hours else "ok", _("Vulnerabilities in the libraries"),
                  _("None known on %(date)s.", date=when) + " " + auto, "vulnerabilities", "advisories")

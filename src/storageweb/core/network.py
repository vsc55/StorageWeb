"""Diagnóstico de red: cómo llega una petición y si cuadra con la configuración (proxy, HTTPS, FQDN).

Sin Flask: la web le pasa lo que ve de la petición (``facts``) y las cabeceras ``X-Forwarded-*``.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from ..i18n import _

FORWARDED_HEADERS = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Forwarded-Port",
                     "X-Forwarded-Prefix")
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def diagnose(facts: dict, headers: dict, cfg: dict, boot: dict) -> dict:
    """Avisos (``notes``: ``(nivel, texto)`` con nivel ok | info | warn | danger) y datos para los ejemplos.

    ``facts``: ``scheme``, ``host``, ``prefix``, ``client``, ``peer`` y ``base`` de la petición.
    ``cfg`` son los ajustes efectivos y ``boot`` los de arranque.
    """
    server, public = boot["server"], cfg["network"]["public_url"]
    behind_proxy, cookie_secure = server["behind_proxy"], boot["session"]["cookie_secure"]
    scheme, host = facts["scheme"], facts["host"]
    pub = urlsplit(public) if public else None
    notes: list[tuple[str, str]] = []

    if any(headers.values()) and not behind_proxy:
        notes.append(("warn", _("The request carries X-Forwarded-* headers but server.behind_proxy is disabled: they "
                                "are ignored, so the client address and the scheme are those of the proxy.")))
    if behind_proxy and not headers.get("X-Forwarded-For"):
        level = "danger" if server["host"] not in LOOPBACK else "warn"
        notes.append((level, _("server.behind_proxy is enabled but this request has no X-Forwarded-For: it did not "
                               "go through the proxy.")
                      + (" " + _("The service listens on %(host)s, so anyone who reaches it directly can fake their "
                                 "address. Listen on 127.0.0.1.", host=server["host"]) if level == "danger" else "")))
    if not public:
        notes.append(("info", _("There is no public address: external URLs use the host of each request (%(base)s "
                                "now). Set it if users can arrive through more than one name.", base=facts["base"])))
    else:
        if pub.scheme == "https" and scheme != "https":
            notes.append(("warn", _("The public address is HTTPS but the application sees this request as HTTP: the "
                                    "proxy does not send X-Forwarded-Proto or server.behind_proxy is disabled.")))
        if pub.netloc.lower() != host.lower():
            notes.append(("info", _("You are using %(host)s; the public address is %(public)s.", host=host,
                                    public=public)))
        if pub.scheme == "http" and pub.hostname not in LOOPBACK:
            notes.append(("warn", _("The public address is not HTTPS: Entra ID only accepts HTTPS return addresses "
                                    "and passwords travel in clear text.")))
    if cookie_secure and scheme != "https" and not public:
        notes.append(("warn", _("The session cookie is HTTPS-only but the application sees this request as HTTP: "
                                "the proxy probably does not send X-Forwarded-Proto. Generated URLs will be http://.")))
    if not cookie_secure and (scheme == "https" or (pub and pub.scheme == "https")):
        notes.append(("warn", _("session.cookie_secure is disabled: enable it in production (config.json).")))
    redirect_uri = cfg["auth"]["entra"].get("redirect_uri")
    if redirect_uri and public and not redirect_uri.startswith(public + "/"):
        notes.append(("warn", _("The Entra ID redirect URI (%(uri)s) does not use the public address.",
                                uri=redirect_uri)))
    if not any(level in ("warn", "danger") for level, _text in notes):
        notes.insert(0, ("ok", _("The proxy, the scheme and the public address match.")))

    target = pub or urlsplit(facts["base"])
    return {"seen": facts, "forwarded": headers, "notes": notes, "boot_server": server, "cookie_secure": cookie_secure,
            "example": {"host": target.hostname or "files.example.com", "prefix": (target.path or "").rstrip("/"),
                        "upstream": f"{'127.0.0.1' if server['host'] in ('0.0.0.0', '::') else server['host']}"
                                    f":{server['port']}",
                        "body_mb": server["max_upload_mb"] + 16}}


def warnings(diagnosis: dict) -> list[tuple[str, str]]:
    """Solo los avisos que hay que atender (``warn`` y ``danger``)."""
    return [(level, text) for level, text in diagnosis["notes"] if level in ("warn", "danger")]

"""Comprobación de la configuración de Entra ID sin que nadie inicie sesión.

1. **Tenant**: descarga los metadatos OIDC (``.well-known/openid-configuration``).
2. **Aplicación y Redirect URI**: pide ``/authorize`` con ``prompt=none`` sin seguir la
   redirección. Si Entra redirige a nuestra URI, la aplicación existe y la URI está registrada;
   si no, la página de error trae el código ``AADSTS`` que explica el motivo.
3. **Secreto**: pide un token de aplicación (``client_credentials``) al endpoint de token. No se
   usa para nada más.

Con endpoints propios (otro proveedor OIDC) solo se comprueban los metadatos del ``issuer``.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from ...i18n import _
from . import oauth2
from .common import MS_LOGIN, endpoints

GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, PLR0913
        return None


def _http_get(url: str, timeout: float) -> tuple[int, dict, str]:
    """GET sin seguir redirecciones: (estado, cabeceras, cuerpo). Lanza OSError si no hay red."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"Accept": "application/json, text/html"})
    try:
        with opener.open(request, timeout=timeout) as resp:  # noqa: S310 (URL de la configuración)
            return resp.status, dict(resp.headers), resp.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read(200_000).decode("utf-8", "replace")


def _result(key: str, ok: bool | None, message: str) -> dict:
    return {"key": key, "ok": ok, "message": message}


def _uses_microsoft(ecfg: dict) -> bool:
    return not any(ecfg.get(k) for k in ("authorize_url", "token_url", "issuer"))


def check(ecfg: dict, redirect_uri: str) -> list[dict]:
    """Devuelve una lista de resultados ``{key, ok (True/False/None), message}``."""
    timeout = float(ecfg.get("timeout_seconds") or 10)
    eps = endpoints(ecfg)
    results = []

    # 1. metadatos
    if _uses_microsoft(ecfg):
        metadata_url = f"{MS_LOGIN}/{ecfg.get('tenant_id', '')}/v2.0/.well-known/openid-configuration"
    else:
        metadata_url = eps["issuer"].rstrip("/") + "/.well-known/openid-configuration"
    try:
        status, _headers, body = _http_get(metadata_url, timeout)
    except OSError as exc:
        return [_result("metadata", False, _("Could not reach %(url)s: %(error)s", url=metadata_url, error=exc))]
    if status == 200:
        results.append(_result("metadata", True, _("The tenant exists and answers (OIDC metadata downloaded).")))
    else:
        results.append(_result("metadata", False, _("The tenant does not exist or does not answer (HTTP %(status)s).",
                                                    status=status)))
        return results

    if not _uses_microsoft(ecfg):
        results.append(_result("redirect", None, _("Custom endpoints: the application and the secret are checked on "
                                                   "the first sign-in.")))
        return results

    # 2. aplicación y redirect URI
    query = urllib.parse.urlencode({"client_id": ecfg.get("client_id", ""), "redirect_uri": redirect_uri,
                                    "response_type": "code", "scope": "openid", "prompt": "none",
                                    "state": "storageweb-check"})
    try:
        status, headers, body = _http_get(f"{eps['authorize']}?{query}", timeout)
    except OSError as exc:
        status, headers, body = 0, {}, str(exc)
    location = headers.get("Location") or headers.get("location") or ""
    if status in (301, 302, 303) and location.startswith(redirect_uri):
        results.append(_result("client", True, _("The application exists in the tenant.")))
        results.append(_result("redirect", True, _("The redirect URI is registered in the application.")))
    elif "AADSTS700016" in body:
        results.append(_result("client", False, _("The Client ID does not exist in this tenant.")))
    elif "AADSTS50011" in body:
        results.append(_result("client", True, _("The application exists in the tenant.")))
        results.append(_result("redirect", False, _("The redirect URI %(uri)s is not registered in the application "
                                                    "(Authentication → Web).", uri=redirect_uri)))
    else:
        results.append(_result("redirect", None, _("The redirect URI could not be checked (HTTP %(status)s).",
                                                   status=status)))

    # 3. secreto
    if not ecfg.get("client_secret"):
        results.append(_result("secret", False, _("There is no client secret.")))
        return results
    try:
        token = oauth2._http_post(eps["token"], {"grant_type": "client_credentials",
                                                 "client_id": ecfg.get("client_id", ""),
                                                 "client_secret": ecfg["client_secret"],
                                                 "scope": GRAPH_DEFAULT_SCOPE}, timeout)
    except Exception as exc:  # noqa: BLE001 (cualquier fallo de red se muestra tal cual)
        results.append(_result("secret", None, _("The secret could not be checked: %(error)s", error=exc)))
        return results
    description = str(token.get("error_description", ""))
    if token.get("access_token"):
        results.append(_result("secret", True, _("The client secret is valid.")))
        from .directory import can_read_groups  # noqa: PLC0415 (evita un import circular)
        ok, detail = can_read_groups(token["access_token"])
        results.append(_result("groups", ok, _("The application can read group names (Group.Read.All).") if ok
                               else _("The application cannot read group names: %(error)s. Use «Grant group "
                                      "reading» to see names instead of Object IDs.", error=detail)))
    elif "AADSTS7000222" in description:
        results.append(_result("secret", False, _("The client secret has expired: create a new one.")))
    elif "AADSTS7000215" in description:
        results.append(_result("secret", False, _("The client secret is not valid (copy the value, not the ID).")))
    else:
        results.append(_result("secret", False, _("The token endpoint answered: %(error)s",
                                                  error=(description.splitlines() or [token.get("error", "?")])[0])))
    return results


def summary(results: list[dict]) -> bool | None:
    """True si todo bien, False si algo falla, None si quedó algo sin comprobar."""
    if any(r["ok"] is False for r in results):
        return False
    return True if all(r["ok"] for r in results) else None


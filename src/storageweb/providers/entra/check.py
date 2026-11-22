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

from ...i18n import _, _l, format_datetime
from . import oauth2
from .common import app_token_request, custom_endpoints, endpoints, MS_LOGIN



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
    return not custom_endpoints(ecfg)


# Permisos de aplicación (sin usuario) que usa StorageWeb, para qué y la clave de su resultado
APP_PERMISSIONS = {
    "Group.Read.All": _l("to show group names instead of Object IDs"),
    "User.Read.All": _l("to disable accounts removed or disabled in Entra ID, refresh groups between sign-ins and "
                        "read the groups of users in more than 200"),
}
PERMISSION_KEYS = {"Group.Read.All": "groups", "User.Read.All": "users"}


def _app_roles(access_token: str) -> set[str]:
    """Permisos de aplicación concedidos (con consentimiento de administrador): el claim ``roles`` del token."""
    try:
        return set(oauth2.decode_jwt_claims(access_token).get("roles") or [])
    except Exception:  # noqa: BLE001 (un token raro no debe romper la comprobación)
        return set()


def _signin_scopes(ecfg: dict, last_signin: dict | None) -> dict:
    """Los permisos de inicio de sesión (delegados) solo se ven cuando alguien entra: se comparan con los que
    Microsoft concedió en el último inicio de sesión (``core.accounts.last_signin_scopes``)."""
    wanted = [s for s in oauth2.scopes_for(ecfg) if s != "offline_access"]
    if not last_signin or not isinstance(last_signin.get("scopes"), list):
        return {**_result("signin_scopes", None, _("Sign-in permissions (%(scopes)s): they are checked when someone "
                                                   "signs in with Microsoft.", scopes=", ".join(wanted))), "info": True}
    granted = {str(s).lower() for s in last_signin["scopes"]}
    missing = [s for s in wanted if s.lower() not in granted]
    when = format_datetime(last_signin.get("at") or "")
    if not missing and last_signin.get("source") == "consent":
        return _result("signin_scopes", True, _("Sign-in permissions with admin consent (%(scopes)s), given when "
                                                "StorageWeb registered or repaired the application (%(when)s).",
                                                scopes=", ".join(wanted), when=when))
    if not missing:
        return _result("signin_scopes", True, _("Sign-in permissions granted (%(scopes)s), according to the last "
                                                "sign-in (%(when)s).", scopes=", ".join(wanted), when=when))
    return {**_result("signin_scopes", False, _("Sign-in permissions missing: %(missing)s (last sign-in: "
                                                 "%(when)s). They need admin consent.",
                                                 missing=", ".join(missing), when=when)), "fixable": True}


def check(ecfg: dict, redirect_uri: str, secret_is_new: bool = False, last_signin: dict | None = None) -> list[dict]:
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
        results.append({**_result("redirect", False, _("The redirect URI %(uri)s is not registered in the "
                                                       "application (Authentication → Web).", uri=redirect_uri)),
                        "fixable": True})
    else:
        results.append(_result("redirect", None, _("The redirect URI could not be checked (HTTP %(status)s).",
                                                   status=status)))

    # 3. secreto
    if not ecfg.get("client_secret"):
        results.append(_result("secret", False, _("There is no client secret.")))
        return results
    try:
        token = app_token_request(ecfg, timeout)
    except Exception as exc:  # noqa: BLE001 (cualquier fallo de red se muestra tal cual)
        results.append(_result("secret", None, _("The secret could not be checked: %(error)s", error=exc)))
        return results
    description = str(token.get("error_description", ""))
    if token.get("access_token"):
        results.append(_result("secret", True, _("The client secret is valid.")))
        from .directory import can_read_groups, can_read_users  # noqa: PLC0415 (evita un import circular)
        roles = _app_roles(token["access_token"])
        works = {"Group.Read.All": can_read_groups, "User.Read.All": can_read_users}
        # 4. permisos de aplicación: cada uno que usa StorageWeb, y si funciona de verdad
        for perm, purpose in APP_PERMISSIONS.items():
            key = PERMISSION_KEYS.get(perm, perm)
            if perm not in roles:
                results.append({**_result(key, False,
                                          _("Application permission %(perm)s is not granted with admin consent "
                                            "(%(purpose)s).", perm=perm, purpose=purpose)), "fixable": True})
                continue
            ok, detail = works[perm](token["access_token"]) if perm in works else (True, "")
            results.append({**_result(key, ok,
                                      _("Application permission %(perm)s granted (%(purpose)s).", perm=perm,
                                        purpose=purpose) if ok
                                      else _("Application permission %(perm)s is granted but does not work yet: "
                                             "%(error)s", perm=perm, error=detail)), "fixable": not ok})
        extra = sorted(roles - set(APP_PERMISSIONS))
        if extra:
            results.append({**_result("extra_permissions", None, _(
                "The application also has application permissions that StorageWeb does not use: %(perms)s. Remove "
                "them in the Entra admin center if nothing else needs them (least privilege).",
                perms=", ".join(extra))), "info": True})
    elif "AADSTS7000222" in description:
        results.append({**_result("secret", False, _("The client secret has expired: create a new one.")),
                        "fixable": True})
    elif "AADSTS7000215" in description and secret_is_new:
        # Un secreto recién creado tarda en valer en todos los servidores de Microsoft: no es un error todavía
        results.append({**_result("secret", None, _("Microsoft is still activating the new client secret (it can "
                                                    "take a minute). It is checked again automatically.")),
                        "pending": True})
    elif "AADSTS7000215" in description:
        results.append({**_result("secret", False, _("The client secret is not valid (copy the value, not the ID).")),
                        "fixable": True})
    else:
        results.append(_result("secret", False, _("The token endpoint answered: %(error)s",
                                                  error=(description.splitlines() or [token.get("error", "?")])[0])))
    # 5. permisos de inicio de sesión (delegados) y claims del id_token, según el último inicio de sesión
    results.append(_signin_scopes(ecfg, last_signin))
    claims = _signin_claims(last_signin)
    if claims is not None:
        results.append(claims)
    return results


def _signin_claims(last_signin: dict | None) -> dict | None:
    """Si el id_token del último inicio de sesión traía ``sid`` (sin él, cerrar sesión en Microsoft no cierra la de
    StorageWeb). ``None`` si aún no se sabe."""
    if not last_signin or last_signin.get("source") != "signin" or not isinstance(last_signin.get("claims"), list):
        return None
    when = format_datetime(last_signin.get("at") or "")
    if "sid" in last_signin["claims"]:
        return _result("claims", True, _("The ID token includes the session (sid): signing out of Microsoft also "
                                         "closes StorageWeb (last sign-in: %(when)s).", when=when))
    return {**_result("claims", False, _("The ID token does not include the session (sid) claim: signing out of "
                                         "Microsoft will not close StorageWeb (last sign-in: %(when)s).", when=when)),
            "fixable": True}


def repairs(results: list[dict]) -> dict | None:
    """Lo que «Reparar automáticamente» puede arreglar de los fallos encontrados (``None`` si nada):
    ``{"new_secret": bool}`` (el resto se revisa y arregla siempre)."""
    fixable = [r for r in results if r.get("ok") is False and r.get("fixable")]
    if not fixable:
        return None
    return {"new_secret": any(r["key"] == "secret" for r in fixable)}


def summary(results: list[dict]) -> bool | None:
    """True si todo bien, False si algo falla, None si quedó algo sin comprobar (los avisos informativos, como
    los permisos de más o los de inicio de sesión que aún no se han podido ver, no cuentan)."""
    if any(r["ok"] is False for r in results):
        return False
    return True if all(r["ok"] for r in results if not r.get("info")) else None


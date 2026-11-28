// @ts-check
"use strict";
/**
 * Iniciar sesión en el navegador para conseguir el token (OAuth con PKCE; en el servidor,
 * core/connect.py). Sin VS Code:
 *
 * 1. `startRequest` inventa un `verifier` secreto y da la dirección de `/connect/vscode` con su SHA-256
 *    (`challenge`), un `state` y la vuelta (`vscode://storageweb.storageweb-sync/auth`).
 * 2. El usuario inicia sesión y acepta en el navegador; StorageWeb vuelve a VS Code con `code` y `state`.
 * 3. `exchange` canjea el código con el verifier y recibe el usuario y el token.
 *
 * Y, sin navegador, con la cuenta del equipo (`desktopMethods`, `redeemDesktop`: más abajo).
 */

const crypto = require("crypto");

/** @param {Buffer} buf */
function base64url(buf) {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** @param {string} verifier */
function challengeOf(verifier) {
  return base64url(crypto.createHash("sha256").update(verifier, "ascii").digest());
}

/**
 * @param {string} server  dirección de StorageWeb (sin barra final)
 * @param {string} callback  la vuelta a VS Code (vscode://storageweb.storageweb-sync/auth)
 * @param {string} device  nombre del equipo (para el nombre del token)
 * @returns {{state: string, verifier: string, url: string}}
 */
function startRequest(server, callback, device) {
  const verifier = base64url(crypto.randomBytes(48));
  const state = base64url(crypto.randomBytes(24));
  const query = new URLSearchParams({ redirect_uri: callback, challenge: challengeOf(verifier), state, device });
  return { state, verifier, url: `${server.replace(/\/+$/, "")}/connect/vscode?${query}` };
}

class ConnectError extends Error {
  /** @param {string} code @param {string} message @param {string} [serverMessage] lo que explicó el servidor */
  constructor(code, message, serverMessage = "") {
    super(message);
    this.code = code;
    this.serverMessage = serverMessage;
  }
}

/**
 * @param {string} server @param {string} code @param {string} verifier
 * @param {{fetch?: typeof fetch, timeoutMs?: number}} [options]
 * @returns {Promise<{username: string, token: string, name: string, days: number}>}
 */
async function exchange(server, code, verifier, options = {}) {
  const doFetch = options.fetch || fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || 30000);
  let resp;
  try {
    resp = await doFetch(`${server.replace(/\/+$/, "")}/connect/token`, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ code, verifier }), signal: controller.signal, redirect: "manual",
    });
  } catch (err) {
    throw new ConnectError("network", `Cannot connect to the server: ${err && err.message ? err.message : err}`);
  } finally {
    clearTimeout(timer);
  }
  if (resp.status === 404 || resp.status === 405) {
    throw new ConnectError("unsupported", "This StorageWeb does not support signing in from the browser");
  }
  if (resp.status === 403) throw new ConnectError("tokens_disabled", "API tokens are disabled on this StorageWeb");
  if (resp.status !== 200) throw new ConnectError("invalid_grant", `The server did not accept the sign-in (HTTP ${resp.status})`);
  const data = /** @type {any} */ (await resp.json());
  if (!data || typeof data.token !== "string" || typeof data.username !== "string") {
    throw new ConnectError("invalid_grant", "Unexpected answer from the server");
  }
  return { username: data.username, token: data.token, name: String(data.name || ""), days: Number(data.days) || 0 };
}

/** La vuelta del navegador (`?code=…&state=…` o `?error=…&state=…`). @param {string} query */
function parseCallback(query) {
  const params = new URLSearchParams(query);
  return { code: params.get("code") || "", state: params.get("state") || "", error: params.get("error") || "" };
}

// --------------------------------------------------------------------------- con la cuenta del equipo
/*
 * Entrar sin navegador con la cuenta con la que se inició sesión en el equipo (Windows unido a Microsoft
 * Entra ID): `desktopMethods` pregunta al servidor qué métodos admite (`GET /connect/desktop`); la extensión
 * pide a VS Code un token de ese proveedor (`vscode.authentication.getSession`, que en Windows usa el agente
 * de cuentas del sistema) y `redeemDesktop` lo canjea por un token de API de StorageWeb
 * (`POST /connect/desktop`).
 */

/**
 * @typedef {{key: string, label: string, provider: string, tenant: string, scopes: string[]}} DesktopMethod
 */

const GUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
/** El único permiso que se pide a Microsoft: el de entrar en una StorageWeb (`api://<client_id>/access_as_user`). */
const MICROSOFT_SCOPE = new RegExp(`^api://${GUID}/access_as_user$`, "i");
/** Un tenant: su id, un dominio (contoso.onmicrosoft.com) o los multi-tenant; nada con `:` ni espacios. */
const MICROSOFT_TENANT = new RegExp(`^(?:${GUID}|organizations|common|(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63})$`, "i");

/**
 * Lo que anuncia el servidor se usa para pedir un token con la cuenta del equipo **sin preguntar nada** y ese
 * token se le manda: un servidor malicioso no puede elegir qué se pide (Microsoft Graph, otro `VSCODE_CLIENT_ID:`,
 * otro tenant con caracteres raros…). Solo Microsoft, un único permiso `access_as_user` y un tenant con forma de
 * tenant. @param {any} m
 */
function safeMethod(m) {
  return Boolean(m && typeof m.key === "string" && m.key && m.provider === "microsoft"
    && Array.isArray(m.scopes) && m.scopes.length === 1 && typeof m.scopes[0] === "string"
    && MICROSOFT_SCOPE.test(m.scopes[0])
    && (m.tenant === undefined || m.tenant === "" || (typeof m.tenant === "string" && MICROSOFT_TENANT.test(m.tenant))));
}

/**
 * Si se puede usar la cuenta del equipo con este servidor: solo por HTTPS (o el propio equipo). Por http, quien esté
 * en medio cambiaría lo que se pide y se llevaría el token. @param {string} server
 */
function secureServer(server) {
  try {
    const url = new URL(server);
    return url.protocol === "https:" || ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  } catch {
    return false;
  }
}

/**
 * La huella de lo que se pide a Microsoft para un servidor (la aplicación y el tenant). Se guarda la primera vez
 * que sale bien: si un servidor pide luego el token de otra aplicación (otra StorageWeb, para usarlo allí), no se
 * pide sin preguntar. @param {DesktopMethod} method
 */
function methodPin(method) {
  return `${method.scopes[0].toLowerCase()}|${method.tenant.toLowerCase()}`;
}

/**
 * Los métodos para entrar con la cuenta del equipo que anuncia el servidor. Un servidor antiguo (404), uno
 * que no responde o una respuesta rara: ninguno (la opción no se ofrece).
 * @param {string} server
 * @param {{fetch?: typeof fetch, timeoutMs?: number}} [options]
 * @returns {Promise<DesktopMethod[]>}
 */
async function desktopMethods(server, options = {}) {
  const doFetch = options.fetch || fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || 10000);
  try {
    const resp = await doFetch(`${server.replace(/\/+$/, "")}/connect/desktop`, {
      method: "GET", headers: { Accept: "application/json" }, signal: controller.signal, redirect: "manual",
    });
    if (resp.status !== 200) return [];
    const data = /** @type {any} */ (await resp.json());
    const methods = data && Array.isArray(data.methods) ? data.methods : [];
    return methods.filter(safeMethod).map((m) => ({
      key: m.key, label: typeof m.label === "string" && m.label ? m.label : m.key, provider: m.provider,
      tenant: m.tenant || "", scopes: [...m.scopes],
    }));
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Los permisos que se piden al proveedor de VS Code: los del servidor y, con Microsoft, el inquilino
 * (`VSCODE_TENANT:…`, salvo `organizations`/`common`, que son los de por defecto).
 * @param {DesktopMethod} method
 */
function sessionScopes(method) {
  const scopes = [...method.scopes];
  const tenant = method.tenant.toLowerCase();
  if (method.provider === "microsoft" && tenant && tenant !== "organizations" && tenant !== "common") {
    scopes.push(`VSCODE_TENANT:${method.tenant}`);
  }
  return scopes;
}

/** Lo que dice cada error de `POST /connect/desktop` si el servidor no trae su `message`. */
const DESKTOP_ERRORS = {
  tokens_disabled: "API tokens are disabled on this StorageWeb",
  not_enabled: "This StorageWeb does not allow signing in with the account of the computer",
  unknown_client: "This StorageWeb does not know this client",
  invalid_token: "StorageWeb did not accept the token of the account",
  denied: "This account cannot sign in to StorageWeb",
};

/**
 * Canjea el token del proveedor (Microsoft) por un token de API de StorageWeb para este equipo. Los errores,
 * `ConnectError` con el `code` del servidor (`tokens_disabled`, `not_enabled`, `unknown_client`,
 * `invalid_token`, `denied`; o `network`, `failed`) y, en `serverMessage`, la explicación del servidor.
 * @param {string} server @param {DesktopMethod} method @param {string} accessToken @param {string} device
 * @param {{fetch?: typeof fetch, timeoutMs?: number, language?: string, client?: string}} [options]
 * @returns {Promise<{username: string, token: string, name: string, days: number}>}
 */
async function redeemDesktop(server, method, accessToken, device, options = {}) {
  const doFetch = options.fetch || fetch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || 30000);
  /** @type {Record<string, string>} */
  const headers = { "Content-Type": "application/json", Accept: "application/json" };
  if (options.language) headers["Accept-Language"] = options.language;  // el `message` del servidor, en su idioma
  let resp;
  try {
    resp = await doFetch(`${server.replace(/\/+$/, "")}/connect/desktop`, {
      method: "POST", headers, signal: controller.signal, redirect: "manual",
      body: JSON.stringify({ method: method.key, client: options.client || "vscode", access_token: accessToken, device }),
    });
  } catch (err) {
    throw new ConnectError("network", `Cannot connect to the server: ${err && /** @type {any} */ (err).message ? /** @type {any} */ (err).message : err}`);
  } finally {
    clearTimeout(timer);
  }
  /** @type {any} */
  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  if (resp.status === 200) {
    if (!data || typeof data.token !== "string" || typeof data.username !== "string") {
      throw new ConnectError("failed", "Unexpected answer from the server");
    }
    return { username: data.username, token: data.token, name: String(data.name || ""), days: Number(data.days) || 0 };
  }
  let code = data && typeof data.error === "string" ? data.error : "";
  if (!code) {
    code = resp.status === 404 || resp.status === 405 ? "not_enabled"
      : resp.status === 401 ? "invalid_token" : resp.status === 403 ? "denied" : "failed";
  }
  const serverMessage = data && typeof data.message === "string" ? data.message.trim() : "";
  const fallback = /** @type {Record<string, string>} */ (DESKTOP_ERRORS)[code]
    || `The server did not accept the sign-in (HTTP ${resp.status})`;
  throw new ConnectError(code, serverMessage || fallback, serverMessage);
}

module.exports = {
  startRequest, exchange, parseCallback, challengeOf, ConnectError, desktopMethods, redeemDesktop, sessionScopes,
  secureServer, methodPin,
};

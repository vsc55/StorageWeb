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
  /** @param {string} code @param {string} message */
  constructor(code, message) {
    super(message);
    this.code = code;
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

module.exports = { startRequest, exchange, parseCallback, challengeOf, ConnectError };

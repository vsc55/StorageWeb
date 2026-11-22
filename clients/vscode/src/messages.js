// @ts-check
"use strict";
/**
 * Qué decirle a la persona cuando el servidor deniega algo. StorageWeb explica el motivo en la cabecera
 * `X-StorageWeb-Reason` de sus errores (dav.js lo guarda en `DavError.code`; remotefs.js, en
 * `RemoteFsError.serverCode`):
 *
 * - 401: `account_disabled`, `token_expired`, `token_invalid`, `tokens_disabled`, `password_not_allowed`,
 *   `mfa_requires_token`, `throttled`; sin código, usuario o token rechazados.
 * - 403: `ip_banned`, `read_only`, `token_read_only`, `no_permission`.
 * - 503: `maintenance` (restaurando una copia: pasajero). 413: `too_large`.
 * - Estado 0: sin red, o `interrupted` (una descarga cortada a medias).
 *
 * Lo usan los avisos de la sincronización (extension.js), los paneles (views.js) y los archivos `storageweb://`
 * (provider.js), para que digan lo mismo.
 */

const vscode = require("vscode");

const { DavError } = require("./dav");

const t = vscode.l10n.t;

/** 401 que se arreglan con otro token (iniciar sesión otra vez o pegar uno nuevo). */
const TOKEN_FIXABLE = new Set(["", "token_expired", "token_invalid", "password_not_allowed", "mfa_requires_token"]);

/** Escrituras que el servidor no deja hacer por permisos (403). */
const DENIED = new Set(["read_only", "token_read_only", "no_permission"]);

/** @param {unknown} err @returns {number | undefined} */
function statusOf(err) {
  const status = err && typeof err === "object" ? /** @type {any} */ (err).status : undefined;
  return typeof status === "number" ? status : undefined;
}

/** El código de StorageWeb de un error de dav.js o de remotefs.js ("" si no tiene). @param {unknown} err */
function codeOf(err) {
  if (err instanceof DavError) return err.code || "";
  const code = err && typeof err === "object" ? /** @type {any} */ (err).serverCode : "";
  return typeof code === "string" ? code : "";
}

/** El servidor no acepta las credenciales (o la cuenta), con cualquier motivo. @param {unknown} err */
function isRejected(err) {
  return statusOf(err) === 401
    || (err instanceof Error && err.message.startsWith("The server rejected"));
}

/** ¿Se arregla con otro token? (401 sin código, caducado, revocado, contraseña no admitida…) @param {unknown} err */
function needsToken(err) {
  return isRejected(err) && TOKEN_FIXABLE.has(codeOf(err));
}

/**
 * Por qué no se puede escribir en una carpeta (403 de permisos), como final de frase: «… porque {texto}».
 * @param {string} code
 */
function deniedReason(code) {
  switch (code) {
    case "read_only": return t("the folder is read-only for you");
    case "token_read_only": return t("the API token only allows reading");
    case "no_permission": return t("your role does not allow uploading or deleting files");
    default: return t("the server does not allow it");
  }
}

/**
 * La explicación de un código de StorageWeb (o de `interrupted`), o "" si no es uno conocido.
 * @param {string} code @param {number} [status]
 */
function reasonText(code, status) {
  switch (code) {
    case "account_disabled": return t("Your StorageWeb account is disabled: ask an administrator.");
    case "token_expired": return t("The API token has expired: sign in again or set a new token.");
    case "token_invalid": return t("The server does not recognize the API token (revoked or deleted): sign in again or set a new token.");
    case "tokens_disabled": return t("This StorageWeb no longer accepts API tokens: ask an administrator.");
    case "password_not_allowed": return t("The server does not accept the account password here: use an API token.");
    case "mfa_requires_token": return t("Your account uses two-step verification: connect with an API token (sign in with the browser).");
    case "throttled": return t("Too many failed attempts: wait a few minutes before trying again.");
    case "ip_banned": return t("The server has blocked the IP address of this computer: ask an administrator.");
    case "maintenance": return t("The server is in maintenance (restoring a backup): try again in a moment.");
    case "too_large": return t("The file is larger than the server allows.");
    case "interrupted": return t("The transfer was interrupted before it finished: nothing was saved. Try again.");
    default:
      if (status === 403 && DENIED.has(code)) return t("Not allowed: {0}.", deniedReason(code));
      return "";
  }
}

/** Un error del cliente, de remotefs o de VS Code, en una frase para la persona. @param {unknown} err */
function describe(err) {
  const status = statusOf(err), code = codeOf(err);
  const known = reasonText(code, status);
  if (known) return known;
  if (isRejected(err)) return t("The server rejected the user or the token.");
  if (status === 413) return reasonText("too_large");
  if (status === 502 || status === 503 || status === 504) {
    return t("The server is not responding right now (HTTP {0}): try again in a moment.", status);
  }
  const where = err && typeof err === "object" ? /** @type {any} */ (err).path : undefined;
  const notFound = status === 404 || (err && typeof err === "object" && /** @type {any} */ (err).code === "FileNotFound");
  if (notFound && typeof where === "string") {
    // /dav/ entero no existe: el servidor no tiene la unidad de red; una ruta: ya no está o ya no hay acceso
    if (!where.split("/").filter(Boolean).length) {
      return status === 404 ? t("This StorageWeb does not have the network drive (WebDAV) enabled.")
        : err instanceof Error ? err.message : String(err);
    }
    return t("«{0}» does not exist on the server, or you no longer have access to it.", where);
  }
  return err instanceof Error ? err.message : String(err);
}

module.exports = { DENIED, codeOf, deniedReason, describe, isRejected, needsToken, reasonText, statusOf };

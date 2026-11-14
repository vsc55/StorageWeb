// @ts-check
"use strict";
/**
 * Los servidores de StorageWeb que conoce la extensión (varios, cada uno con su usuario).
 *
 * La lista va en el almacén global de la extensión (`globalState`, en este equipo); el token de cada uno,
 * en el almacén de secretos (el del sistema operativo), con la misma clave que usan las carpetas
 * sincronizadas. Sin VS Code: recibe un `memento` ({get, update}) y unos `secrets` ({get, store, delete}).
 */

const crypto = require("crypto");

const KEY = "storageweb.servers";

/** @typedef {{id: string, url: string, username: string, label: string}} ServerProfile */

/** "https://files.empresa.es/" → "https://files.empresa.es" (null si no es una dirección http/https). */
function normalizeUrl(value) {
  let url;
  try {
    url = new URL(String(value || "").trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (url.username || url.password || url.search || url.hash) return null;
  return `${url.protocol}//${url.host}${url.pathname.replace(/\/+$/, "")}`;
}

/** @param {string} url @param {string} username */
function secretKey(url, username) {
  return `storageweb.token:${url}|${username.toLowerCase()}`;
}

/** @param {string} url */
function hostOf(url) {
  try {
    const u = new URL(url);
    return u.host + u.pathname.replace(/\/+$/, "");
  } catch {
    return url;
  }
}

class ServerStore {
  /**
   * @param {{get: (key: string) => any, update: (key: string, value: any) => Thenable<void> | Promise<void>}} memento
   * @param {{get: (key: string) => Thenable<string | undefined> | Promise<string | undefined>,
   *          store: (key: string, value: string) => Thenable<void> | Promise<void>,
   *          delete: (key: string) => Thenable<void> | Promise<void>}} secrets
   */
  constructor(memento, secrets) {
    this.memento = memento;
    this.secrets = secrets;
  }

  /** @returns {ServerProfile[]} por nombre */
  list() {
    const raw = this.memento.get(KEY);
    const all = Array.isArray(raw) ? raw.filter((p) => p && p.id && p.url && p.username) : [];
    return all.map((p) => ({ id: String(p.id), url: String(p.url), username: String(p.username),
      label: String(p.label || "") }))
      .sort((a, b) => this.title(a).localeCompare(this.title(b)));
  }

  /** @param {string} id */
  get(id) {
    return this.list().find((p) => p.id === id);
  }

  /** @param {string} url @param {string} username */
  find(url, username) {
    const clean = normalizeUrl(url);
    return this.list().find((p) => p.url === clean && p.username.toLowerCase() === username.toLowerCase());
  }

  /** El nombre que se muestra: el puesto a mano o la dirección sin «https://». @param {ServerProfile} p */
  title(p) {
    return p.label || hostOf(p.url);
  }

  /**
   * Añade un servidor (o actualiza el que tenga la misma dirección y usuario). `token`, si se da, se guarda.
   * @param {{url: string, username: string, label?: string}} data @param {string} [token]
   * @returns {Promise<ServerProfile>}
   */
  async add(data, token) {
    const url = normalizeUrl(data.url);
    const username = String(data.username || "").trim();
    if (!url) throw new Error(`Invalid address: ${data.url}`);
    if (!username) throw new Error("Missing user name");
    const all = this.list();
    let profile = all.find((p) => p.url === url && p.username.toLowerCase() === username.toLowerCase());
    if (profile) {
      if (data.label !== undefined) profile.label = data.label.trim();
    } else {
      profile = { id: crypto.randomBytes(6).toString("hex"), url, username, label: (data.label || "").trim() };
      all.push(profile);
    }
    await this.memento.update(KEY, all);
    if (token) await this.setToken(profile, token);
    return profile;
  }

  /**
   * Cambia el nombre o la dirección (el usuario no: otra cuenta es otro servidor). Al cambiar la dirección,
   * el token pasa a la clave nueva. @param {string} id @param {{label?: string, url?: string}} changes
   * @returns {Promise<ServerProfile>} el perfil actualizado
   */
  async update(id, changes) {
    const all = this.list();
    const profile = all.find((p) => p.id === id);
    if (!profile) throw new Error(`Unknown server: ${id}`);
    if (changes.label !== undefined) profile.label = changes.label.trim();
    if (changes.url !== undefined) {
      const url = normalizeUrl(changes.url);
      if (!url) throw new Error(`Invalid address: ${changes.url}`);
      if (url !== profile.url) {
        if (all.some((p) => p.id !== id && p.url === url && p.username.toLowerCase() === profile.username.toLowerCase())) {
          throw new Error("There is already a server with that address and user");
        }
        const token = await this.token(profile);
        await this.secrets.delete(secretKey(profile.url, profile.username));
        profile.url = url;
        if (token) await this.secrets.store(secretKey(url, profile.username), token);
      }
    }
    await this.memento.update(KEY, all);
    return profile;
  }

  /** Lo quita de la lista y borra su token de este equipo. @param {string} id */
  async remove(id) {
    const all = this.list();
    const profile = all.find((p) => p.id === id);
    if (!profile) return;
    await this.memento.update(KEY, all.filter((p) => p.id !== id));
    if (!all.some((p) => p.id !== id && p.url === profile.url
        && p.username.toLowerCase() === profile.username.toLowerCase())) {
      await this.secrets.delete(secretKey(profile.url, profile.username));
    }
  }

  /** @param {ServerProfile} profile @returns {Promise<string | undefined>} */
  async token(profile) {
    return (await this.secrets.get(secretKey(profile.url, profile.username))) || undefined;
  }

  /** @param {ServerProfile} profile @param {string} token */
  async setToken(profile, token) {
    await this.secrets.store(secretKey(profile.url, profile.username), token.trim());
  }

  /** @param {ServerProfile} profile */
  async forgetToken(profile) {
    await this.secrets.delete(secretKey(profile.url, profile.username));
  }
}

module.exports = { ServerStore, normalizeUrl, secretKey, hostOf };

// @ts-check
"use strict";
/**
 * Cliente WebDAV mínimo para el servidor de StorageWeb (/dav/).
 *
 * Usa `fetch` de Node (VS Code 1.85+ trae Node 18 o posterior). Autenticación básica con el usuario y
 * un token de API como contraseña. Las rutas son relativas a /dav/ y en formato POSIX
 * ("home/proyecto/src/a.js"); cada parte se codifica al montar la URL.
 */

class DavError extends Error {
  /**
   * `hidden`: el servidor oculta esa ruta para todos (`storage.hidden`): ni existe ni se puede crear.
   * @param {number} status @param {string} message @param {boolean} [hidden]
   */
  constructor(status, message, hidden = false) {
    super(message);
    this.status = status;
    this.hidden = hidden;
  }
}

/** Marca de StorageWeb en las respuestas sobre una ruta oculta para todos (solo de esa ruta, nunca la lista). */
const HIDDEN_HEADER = "X-StorageWeb-Hidden";

/**
 * `label`: el nombre que muestra StorageWeb (en las carpetas de arriba, p. ej. el de una compartida).
 * @typedef {{path: string, name: string, label: string, isDir: boolean, size: number, etag: string, mtime: number}} RemoteEntry
 */

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

/** @param {string} text */
function decodeXml(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (_m, ent) => {
    if (ent[0] === "#") {
      const code = ent[1] === "x" || ent[1] === "X" ? parseInt(ent.slice(2), 16) : parseInt(ent.slice(1), 10);
      return String.fromCodePoint(code);
    }
    return ENTITIES[/** @type {keyof typeof ENTITIES} */ (ent.toLowerCase())];
  });
}

/** Contenido de la primera etiqueta `name` (con cualquier prefijo de espacio de nombres) o null. */
function tag(xml, name) {
  const m = new RegExp(`<(?:[\\w.-]+:)?${name}\\b[^>]*?(?:/>|>([\\s\\S]*?)</(?:[\\w.-]+:)?${name}>)`, "i").exec(xml);
  if (!m) return null;
  return m[1] === undefined ? "" : m[1];
}

/**
 * Respuesta `207 Multi-Status` → entradas. `base` es la ruta de /dav/ en el servidor ("/dav/").
 * @param {string} xml @param {string} base @returns {RemoteEntry[]}
 */
function parseMultistatus(xml, base) {
  if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new DavError(502, "WebDAV response with a DOCTYPE");
  const entries = [];
  const responses = xml.match(/<(?:[\w.-]+:)?response\b[\s\S]*?<\/(?:[\w.-]+:)?response>/gi) || [];
  for (const block of responses) {
    const href = decodeXml((tag(block, "href") || "").trim());
    let path = decodeURIComponent(href.replace(/^[a-z]+:\/\/[^/]+/i, ""));
    if (!path.startsWith(base)) continue;
    path = path.slice(base.length).replace(/\/+$/, "");
    // Solo las propiedades con estado 200 (las que no existen vienen en otro propstat con 404)
    const ok = (block.match(/<(?:[\w.-]+:)?propstat\b[\s\S]*?<\/(?:[\w.-]+:)?propstat>/gi) || [])
      .filter((p) => /\s200\s/.test(tag(p, "status") || " 200 "))
      .join("");
    const type = tag(ok, "resourcetype");
    const isDir = type !== null && /<(?:[\w.-]+:)?collection\b/i.test(type);
    const modified = tag(ok, "getlastmodified");
    entries.push({
      path,
      name: path.split("/").pop() || "",
      label: decodeXml(tag(ok, "displayname") || "").trim(),
      isDir,
      size: isDir ? 0 : parseInt(tag(ok, "getcontentlength") || "0", 10) || 0,
      etag: decodeXml(tag(ok, "getetag") || "").replace(/^W\//, "").replace(/"/g, ""),
      mtime: modified ? Date.parse(decodeXml(modified)) || 0 : 0,
    });
  }
  return entries;
}

class DavClient {
  /**
   * @param {string} server  dirección de StorageWeb ("https://files.empresa.es")
   * @param {string} username
   * @param {string} token   token de API (sw_…)
   * @param {{fetch?: typeof fetch, timeoutMs?: number}} [options]
   */
  constructor(server, username, token, options = {}) {
    const url = new URL(server.replace(/\/+$/, "") + "/dav/");
    this.base = url.pathname;  // "/dav/" (o "/archivos/dav/" con subruta)
    this.root = url.toString();
    this.auth = "Basic " + Buffer.from(`${username}:${token}`, "utf8").toString("base64");
    this.fetch = options.fetch || fetch;
    this.timeoutMs = options.timeoutMs || 60000;
  }

  /** @param {string} path */
  url(path) {
    const parts = path.split("/").filter(Boolean).map(encodeURIComponent);
    return this.root + parts.join("/");
  }

  /**
   * @param {string} method @param {string} path
   * @param {{headers?: Record<string, string>, body?: any, ok?: number[]}} [opts]
   */
  async request(method, path, opts = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let resp;
    try {
      resp = await this.fetch(this.url(path), {
        method,
        headers: { Authorization: this.auth, ...(opts.headers || {}) },
        body: opts.body,
        signal: controller.signal,
        redirect: "manual",
      });
    } catch (err) {
      throw new DavError(0, `Cannot connect to the server: ${err && err.message ? err.message : err}`);
    } finally {
      clearTimeout(timer);
    }
    const ok = opts.ok || [200, 201, 204, 207];
    if (!ok.includes(resp.status)) {
      const hidden = resp.headers.get(HIDDEN_HEADER) === "1";
      throw new DavError(resp.status, `${method} ${path}: HTTP ${resp.status}${hidden ? " (hidden on the server)" : ""}`,
        hidden);
    }
    return resp;
  }

  /** Comprueba usuario y token. @returns {Promise<RemoteEntry[]>} las carpetas de /dav/ */
  async roots() {
    return (await this.list("")).filter((e) => e.isDir);
  }

  /** Contenido de una carpeta (sin ella misma). @param {string} path @returns {Promise<RemoteEntry[]>} */
  async list(path) {
    return (await this.listing(path)).children;
  }

  /**
   * La entrada pedida (`self`, null si el servidor no la devuelve) y lo que tiene dentro.
   * @param {string} path @returns {Promise<{self: RemoteEntry | null, children: RemoteEntry[]}>}
   */
  async listing(path) {
    const resp = await this.request("PROPFIND", path, { headers: { Depth: "1" }, ok: [207] });
    const own = path.split("/").filter(Boolean).join("/");
    const entries = parseMultistatus(await resp.text(), this.base);
    return { self: entries.find((e) => e.path === own) || null, children: entries.filter((e) => e.path !== own) };
  }

  /** La entrada o null si no existe. @param {string} path @returns {Promise<RemoteEntry | null>} */
  async stat(path) {
    try {
      const resp = await this.request("PROPFIND", path, { headers: { Depth: "0" }, ok: [207] });
      return parseMultistatus(await resp.text(), this.base)[0] || null;
    } catch (err) {
      if (err instanceof DavError && err.status === 404) return null;
      throw err;
    }
  }

  /** ¿Oculta para todos en el servidor? (no aparece en los listados, pero no se ha borrado) @param {string} path */
  async isHidden(path) {
    try {
      await this.request("PROPFIND", path, { headers: { Depth: "0" }, ok: [207] });
      return false;
    } catch (err) {
      if (err instanceof DavError && err.hidden) return true;
      if (err instanceof DavError && err.status === 404) return false;
      throw err;
    }
  }

  /**
   * Todos los archivos bajo `path`, recorriendo las carpetas (rutas relativas a `path`).
   * @param {string} path @param {(rel: string, isDir: boolean) => boolean} [skip]
   * @returns {Promise<Map<string, RemoteEntry>>}
   */
  async walk(path, skip) {
    const prefix = path.split("/").filter(Boolean).join("/");
    const files = new Map();
    const pending = [prefix];
    while (pending.length) {
      const dir = /** @type {string} */ (pending.shift());
      for (const entry of await this.list(dir)) {
        const rel = entry.path.slice(prefix.length).replace(/^\/+/, "");
        if (skip && skip(rel, entry.isDir)) continue;
        if (entry.isDir) pending.push(entry.path);
        else files.set(rel, { ...entry, path: rel });
      }
    }
    return files;
  }

  /** @param {string} path @returns {Promise<Buffer>} */
  async get(path) {
    return (await this.download(path)).data;
  }

  /** El contenido y su versión (ETag). @param {string} path @returns {Promise<{data: Buffer, etag: string}>} */
  async download(path) {
    const resp = await this.request("GET", path, { ok: [200] });
    const data = Buffer.from(await resp.arrayBuffer());
    let etag = (resp.headers.get("ETag") || "").replace(/^W\//, "").replace(/"/g, "");
    if (!etag) {
      const entry = await this.stat(path);
      etag = entry ? entry.etag : "";
    }
    return { data, etag };
  }

  /**
   * Sube un archivo. `ifMatch`: solo si el servidor sigue teniendo esa versión; `ifNoneMatch`: solo si no
   * existe. 412 = alguien lo cambió (conflicto). @returns {Promise<string>} la versión nueva (ETag)
   * @param {string} path @param {Buffer} data @param {{ifMatch?: string, ifNoneMatch?: boolean}} [cond]
   */
  async put(path, data, cond = {}) {
    const headers = { "Content-Type": "application/octet-stream" };
    if (cond.ifMatch) headers["If-Match"] = `"${cond.ifMatch}"`;
    if (cond.ifNoneMatch) headers["If-None-Match"] = "*";
    const resp = await this.request("PUT", path, { headers, body: data, ok: [200, 201, 204] });
    const etag = (resp.headers.get("ETag") || "").replace(/^W\//, "").replace(/"/g, "");
    if (etag) return etag;
    const entry = await this.stat(path);
    return entry ? entry.etag : "";
  }

  /**
   * Crea la carpeta y las de encima que falten (la primera parte es una carpeta de StorageWeb, «home»
   * o una compartida, que ya existe). @param {string} path
   */
  async mkdirs(path) {
    const parts = path.split("/").filter(Boolean);
    for (let i = 2; i <= parts.length; i++) {
      await this.request("MKCOL", parts.slice(0, i).join("/"), { ok: [201, 405] });  // 405 = ya existe
    }
  }

  /** Crea una carpeta (la de encima tiene que existir: 409 si no; 405 si ya existe). @param {string} path */
  async mkdir(path) {
    await this.request("MKCOL", path, { ok: [201] });
  }

  /** @param {string} path @param {{ifMatch?: string}} [cond] */
  async remove(path, cond = {}) {
    const headers = {};
    if (cond.ifMatch) headers["If-Match"] = `"${cond.ifMatch}"`;
    await this.request("DELETE", path, { headers, ok: [200, 204, 404] });
  }

  /**
   * Mueve o renombra (archivo o carpeta). Sin `overwrite`, 412 si el destino ya existe.
   * @param {string} from @param {string} to @param {{overwrite?: boolean}} [opts]
   */
  async move(from, to, opts = {}) {
    await this.transfer("MOVE", from, to, opts);
  }

  /** Copia (archivo o carpeta entera). @param {string} from @param {string} to @param {{overwrite?: boolean}} [opts] */
  async copy(from, to, opts = {}) {
    await this.transfer("COPY", from, to, opts);
  }

  /** @param {string} method @param {string} from @param {string} to @param {{overwrite?: boolean}} opts */
  async transfer(method, from, to, opts) {
    const headers = { Destination: this.url(to), Overwrite: opts.overwrite ? "T" : "F" };
    await this.request(method, from, { headers, ok: [201, 204] });
  }
}

module.exports = { DavClient, DavError, parseMultistatus };

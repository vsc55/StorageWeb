// @ts-check
"use strict";
/**
 * Los archivos de un servidor StorageWeb como sistema de archivos, para abrirlos y guardarlos en VS Code
 * sin sincronizar (`storageweb://<servidor>/home/…`). Sin VS Code: provider.js lo adapta a la API.
 *
 * - Cada servidor se identifica por el id de su perfil (servers.js); `clientFor(id)` da su DavClient.
 * - Guardar comprueba la versión del servidor justo antes y la manda en `If-Match`: si cambió entre medias,
 *   el servidor no la pisa (error `Conflict`). VS Code, además, avisa al guardar si el archivo cambió desde
 *   que se abrió (compara la fecha y el tamaño de `stat`), por eso la caché de `stat` dura muy poco.
 * - Los errores son `RemoteFsError` con un `code` como los de VS Code (FileNotFound, FileExists,
 *   FileNotADirectory, FileIsADirectory, NoPermissions, Unavailable) o `Conflict`, `Hidden` (oculto en el
 *   servidor) y `TooLarge`; llevan el estado HTTP y el motivo de StorageWeb (`serverCode`) para explicarlo.
 */

const { DavError } = require("./dav");

class RemoteFsError extends Error {
  /**
   * `status` y `serverCode`: los del error de WebDAV del que viene (el estado HTTP y el motivo que da StorageWeb
   * en `X-StorageWeb-Reason`, p. ej. `read_only` o `account_disabled`; ver messages.js).
   * @param {string} code @param {string} path @param {string} [message] @param {{status?: number, serverCode?: string}} [from]
   */
  constructor(code, path, message, from = {}) {
    super(message || `${code}: ${path}`);
    this.code = code;
    this.path = path;
    this.status = from.status;
    this.serverCode = from.serverCode || "";
  }
}

/** "/home/a/b.txt" → "home/a/b.txt"; "/" → "". Sin «.», «..» ni barras invertidas. @param {string} path */
function cleanPath(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  if (parts.some((p) => p === "." || p === ".." || p.includes("\\"))) {
    throw new RemoteFsError("NoPermissions", path, `Invalid path: ${path}`);
  }
  return parts.join("/");
}

/** @param {string} path */
function parentOf(path) {
  return path.split("/").slice(0, -1).join("/");
}

/**
 * Error del cliente WebDAV → RemoteFsError. `onConflict`: el código para un 412 (cambió en el servidor o
 * el destino ya existe, según la operación). @param {unknown} err @param {string} path @param {string} [onConflict]
 */
function translate(err, path, onConflict = "Conflict") {
  if (err instanceof RemoteFsError) return err;
  if (!(err instanceof DavError)) return err;
  const from = { status: err.status, serverCode: err.code };
  switch (err.status) {
    case 404:
    case 409:  // falta la carpeta de encima
      return new RemoteFsError("FileNotFound", path, err.message, from);
    case 412:
      return new RemoteFsError(onConflict, path, err.message, from);
    case 401:
      return new RemoteFsError("NoPermissions", path, "The server rejected the user or the token", from);
    case 403:  // también la IP bloqueada y las carpetas o tokens de solo lectura (serverCode)
    case 405:
      return new RemoteFsError(err.hidden ? "Hidden" : "NoPermissions", path, err.message, from);
    case 413:  // más grande de lo que admite el servidor
      return new RemoteFsError("TooLarge", path, err.message, from);
    case 0:     // sin red o una descarga cortada a medias
    case 502:
    case 503:   // en mantenimiento (restaurando una copia)
    case 504:
      return new RemoteFsError("Unavailable", path, err.message, from);
    default:
      return err;
  }
}

class RemoteFs {
  /**
   * @param {(server: string) => Promise<import("./dav").DavClient>} clientFor
   * @param {{ttlMs?: number, now?: () => number}} [options]
   */
  constructor(clientFor, options = {}) {
    this.clientFor = clientFor;
    this.ttlMs = options.ttlMs === undefined ? 1500 : options.ttlMs;
    this.now = options.now || Date.now;
    /** @type {Map<string, {entry: import("./dav").RemoteEntry, at: number}>} */
    this.cache = new Map();
  }

  /** @param {string} server @param {string} path */
  key(server, path) {
    return `${server}:${path}`;
  }

  /** Olvida lo que se sabe de un servidor (o de todos). @param {string} [server] */
  forget(server) {
    if (server === undefined) {
      this.cache.clear();
      return;
    }
    for (const k of [...this.cache.keys()]) if (k.startsWith(`${server}:`)) this.cache.delete(k);
  }

  /** Lo cambiado (y, si es una carpeta, lo de dentro) deja de estar en la caché. @param {string} server @param {string} path */
  invalidate(server, path) {
    const prefix = this.key(server, path);
    for (const k of [...this.cache.keys()]) {
      if (k === prefix || k.startsWith(prefix + "/")) this.cache.delete(k);
    }
  }

  /** @param {string} server @param {string} rawPath @returns {Promise<{type: "file" | "dir", size: number, mtime: number, etag: string}>} */
  async stat(server, rawPath) {
    const path = cleanPath(rawPath);
    if (!path) return { type: "dir", size: 0, mtime: 0, etag: "" };
    const hit = this.cache.get(this.key(server, path));
    let entry = hit && this.now() - hit.at < this.ttlMs ? hit.entry : null;
    if (!entry) {
      const client = await this.clientFor(server);
      try {
        entry = await client.stat(path);
      } catch (err) {
        throw translate(err, path);
      }
      if (!entry) throw new RemoteFsError("FileNotFound", path);
      this.cache.set(this.key(server, path), { entry, at: this.now() });
    }
    return { type: entry.isDir ? "dir" : "file", size: entry.size, mtime: entry.mtime, etag: entry.etag };
  }

  /**
   * Lo que hay en una carpeta (las de arriba si `path` es ""), con nombres, tamaños y versiones.
   * @param {string} server @param {string} rawPath @returns {Promise<import("./dav").RemoteEntry[]>}
   */
  async list(server, rawPath) {
    const path = cleanPath(rawPath);
    const client = await this.clientFor(server);
    let listing;
    try {
      listing = await client.listing(path);
    } catch (err) {
      throw translate(err, path);
    }
    if (listing.self && !listing.self.isDir) throw new RemoteFsError("FileNotADirectory", path);
    const at = this.now();
    for (const entry of listing.children) this.cache.set(this.key(server, entry.path), { entry, at });
    return listing.children;
  }

  /** @param {string} server @param {string} path @returns {Promise<[string, "file" | "dir"][]>} */
  async readDirectory(server, path) {
    return (await this.list(server, path)).map((e) => [e.name, e.isDir ? "dir" : "file"]);
  }

  /** @param {string} server @param {string} rawPath @returns {Promise<Buffer>} */
  async readFile(server, rawPath) {
    const path = cleanPath(rawPath);
    if (!path) throw new RemoteFsError("FileIsADirectory", path);
    // GET de una carpeta da una página HTML, no un error: se mira antes (VS Code acaba de pedir stat,
    // así que suele salir de la caché)
    if ((await this.stat(server, path)).type === "dir") throw new RemoteFsError("FileIsADirectory", path);
    const client = await this.clientFor(server);
    try {
      return (await client.download(path)).data;
    } catch (err) {
      throw translate(err, path);
    } finally {
      this.invalidate(server, path);  // la próxima consulta, con la versión que se acaba de leer
    }
  }

  /**
   * Guarda un archivo con la semántica de VS Code: sin `create`, tiene que existir; sin `overwrite`, no.
   * @param {string} server @param {string} rawPath @param {Uint8Array} data
   * @param {{create: boolean, overwrite: boolean}} options @returns {Promise<boolean>} si se creó (no existía)
   */
  async writeFile(server, rawPath, data, options) {
    const path = cleanPath(rawPath);
    if (!path) throw new RemoteFsError("FileIsADirectory", path);
    const client = await this.clientFor(server);
    try {
      const current = await client.stat(path);
      if (current && current.isDir) throw new RemoteFsError("FileIsADirectory", path);
      if (current && !options.overwrite) throw new RemoteFsError("FileExists", path);
      if (!current && !options.create) throw new RemoteFsError("FileNotFound", path);
      await client.put(path, Buffer.from(data), current ? { ifMatch: current.etag } : { ifNoneMatch: true });
      return !current;
    } catch (err) {
      throw translate(err, path);
    } finally {
      this.invalidate(server, path);
    }
  }

  /** @param {string} server @param {string} rawPath */
  async createDirectory(server, rawPath) {
    const path = cleanPath(rawPath);
    if (!path) throw new RemoteFsError("FileExists", path);
    const client = await this.clientFor(server);
    try {
      await client.mkdir(path);
    } catch (err) {
      if (err instanceof DavError && err.status === 405) {  // ya existe (o no se puede crear ahí)
        const entry = await client.stat(path).catch(() => null);
        throw new RemoteFsError(entry ? "FileExists" : "NoPermissions", path, err.message);
      }
      throw translate(err, path);
    } finally {
      this.invalidate(server, path);
    }
  }

  /** Borra un archivo o una carpeta con todo lo de dentro. @param {string} server @param {string} rawPath */
  async delete(server, rawPath) {
    const path = cleanPath(rawPath);
    if (!path) throw new RemoteFsError("NoPermissions", path);
    const client = await this.clientFor(server);
    try {
      if (!(await client.stat(path))) throw new RemoteFsError("FileNotFound", path);
      await client.remove(path);
    } catch (err) {
      throw translate(err, path);
    } finally {
      this.invalidate(server, path);
    }
  }

  /** @param {string} server @param {string} from @param {string} to @param {{overwrite: boolean}} options */
  async rename(server, from, to, options) {
    await this.transfer("move", server, from, to, options);
  }

  /** @param {string} server @param {string} from @param {string} to @param {{overwrite: boolean}} options */
  async copy(server, from, to, options) {
    await this.transfer("copy", server, from, to, options);
  }

  /**
   * @param {"move" | "copy"} op @param {string} server @param {string} rawFrom @param {string} rawTo
   * @param {{overwrite: boolean}} options
   */
  async transfer(op, server, rawFrom, rawTo, options) {
    const from = cleanPath(rawFrom), to = cleanPath(rawTo);
    if (!from || !to) throw new RemoteFsError("NoPermissions", from || to);
    const client = await this.clientFor(server);
    try {
      await client[op](from, to, { overwrite: !!options.overwrite });
    } catch (err) {
      throw translate(err, from, "FileExists");  // 412 = el destino ya existe
    } finally {
      this.invalidate(server, from);
      this.invalidate(server, to);
    }
  }
}

module.exports = { RemoteFs, RemoteFsError, cleanPath, parentOf, translate };

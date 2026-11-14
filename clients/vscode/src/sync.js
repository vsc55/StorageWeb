// @ts-check
"use strict";
/**
 * Motor de sincronización en dos sentidos entre una carpeta local y una carpeta de StorageWeb.
 *
 * Compara tres cosas para cada archivo: lo que hay en local, lo que hay en el servidor y lo que había
 * la última vez que se sincronizó (el «estado»). Así sabe quién cambió qué:
 *
 * | local          | servidor        | acción                                         |
 * |----------------|-----------------|------------------------------------------------|
 * | cambió         | igual           | subir (solo si el servidor sigue igual: If-Match) |
 * | igual          | cambió          | bajar                                          |
 * | cambió         | cambió          | conflicto: se guardan las dos versiones        |
 * | se borró       | igual           | borrar en el servidor                          |
 * | igual          | se borró        | borrar en local (a la papelera)                |
 * | nuevo          | nuevo           | comparar: si son iguales, nada; si no, conflicto |
 *
 * En un conflicto la versión local se guarda como «nombre (conflicto AAAA-MM-DD HHMM).ext» (que se
 * sube también) y la del servidor queda con el nombre original: nunca se pierde nada.
 *
 * No depende de VS Code: recibe un adaptador del disco local y el cliente WebDAV, para poder probarlo.
 */

const crypto = require("crypto");

const { DavError } = require("./dav");

/**
 * La carpeta local contiene dónde guarda el servidor la carpeta remota (p. ej. un StorageWeb de pruebas
 * que guarda sus archivos dentro del proyecto que se sincroniza): cada subida aparecería otra vez en
 * local, dentro de sí misma, sin fin. `localDir`: dónde aparece en local ("" = es la misma carpeta).
 */
class SyncLoopError extends Error {
  /** @param {string} localDir */
  constructor(localDir) {
    super(localDir ? `The local folder contains the server's copy of the remote folder: ${localDir}`
      : "The local folder is the server's copy of the remote folder");
    this.localDir = localDir;
  }
}

const PROBE_PREFIX = ".storageweb-probe-";
const HIDDEN_RETRY_MS = 24 * 3600 * 1000;
const SAVE_EVERY = 200;          // acciones entre guardados del estado (una pasada larga no empieza de cero)
const SAVE_EVERY_MS = 15000;

/** @typedef {{size: number, mtime: number}} LocalEntry */
/**
 * `hidden`: cuándo dijo el servidor que la ruta está oculta para todos (storage.hidden): el archivo se queda
 * solo aquí, sin subirlo ni borrarlo, y se vuelve a probar pasado HIDDEN_RETRY_MS (por si dejó de estarlo).
 * @typedef {{size: number, mtime: number, etag: string, hidden?: number}} StateEntry
 */
/**
 * @typedef {object} LocalFs
 * @property {() => Promise<Map<string, LocalEntry>>} scan
 * @property {(path: string) => Promise<LocalEntry | null>} stat
 * @property {(path: string) => Promise<Buffer>} read
 * @property {(path: string, data: Buffer) => Promise<LocalEntry>} write
 * @property {(path: string) => Promise<void>} remove
 * @property {(path: string, to: string) => Promise<void>} rename
 */
/** @typedef {{type: string, path: string}} Action */

/**
 * Qué hacer con cada archivo. Funciones puras: la misma entrada da siempre el mismo plan.
 * @param {Map<string, LocalEntry>} local @param {Map<string, {etag: string}>} remote
 * @param {Map<string, StateEntry>} state @returns {Action[]}
 */
function plan(local, remote, state) {
  const paths = new Set([...local.keys(), ...remote.keys(), ...state.keys()]);
  /** @type {Action[]} */
  const actions = [];
  for (const path of [...paths].sort()) {
    const l = local.get(path), r = remote.get(path), s = state.get(path);
    if (s && s.hidden) continue;  // oculto en el servidor: se queda solo aquí
    const localChanged = !!l && (!s || l.size !== s.size || l.mtime !== s.mtime);
    const remoteChanged = !!r && (!s || r.etag !== s.etag);
    let type = "";
    if (l && r) {
      if (!s) type = "compare";
      else if (localChanged && remoteChanged) type = "conflict";
      else if (localChanged) type = "upload";
      else if (remoteChanged) type = "download";
    } else if (l) {
      type = s && !localChanged ? "deleteLocal" : "upload";      // borrado en el servidor / nuevo o cambiado aquí
    } else if (r) {
      type = s && !remoteChanged ? "deleteRemote" : "download";  // borrado aquí / nuevo o cambiado allí
    } else if (s) {
      type = "forget";                                            // borrado en los dos sitios
    }
    if (type) actions.push({ type, path });
  }
  return actions;
}

/**
 * «informe.docx» → «informe (conflicto 2026-11-14 1830).docx»
 * @param {string} path @param {string} [label] @param {Date} [date]
 */
function conflictName(path, label = "conflict", date = new Date()) {
  const pad = (/** @type {number} */ n) => String(n).padStart(2, "0");
  const stamp = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}${pad(date.getMinutes())}`;
  const slash = path.lastIndexOf("/");
  const dir = path.slice(0, slash + 1), name = path.slice(slash + 1);
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot) : name, ext = dot > 0 ? name.slice(dot) : "";
  return `${dir}${stem} (${label} ${stamp})${ext}`;
}

class SyncEngine {
  /**
   * @param {object} opts
   * @param {LocalFs} opts.local
   * @param {import("./dav").DavClient} opts.remote
   * @param {string} opts.remoteRoot  carpeta en StorageWeb ("home/proyecto")
   * @param {{load: () => Promise<Map<string, StateEntry>>, save: (s: Map<string, StateEntry>) => Promise<void>}} opts.store
   * @param {(rel: string, isDir?: boolean) => boolean} [opts.skip]
   * @param {(msg: string) => void} [opts.log]
   * @param {string} [opts.conflictLabel]  palabra para las copias en conflicto («conflicto»)
   */
  constructor(opts) {
    this.local = opts.local;
    this.remote = opts.remote;
    this.root = opts.remoteRoot.split("/").filter(Boolean).join("/");
    this.store = opts.store;
    this.skip = opts.skip || (() => false);
    this.log = opts.log || (() => {});
    this.conflictLabel = opts.conflictLabel || "conflict";
    /** @type {Set<string>} carpetas remotas que ya existen */
    this.remoteDirs = new Set();
    this.cancelled = false;
  }

  /** Para la pasada en curso en cuanto termine el archivo que está tratando (se guarda lo hecho). */
  cancel() {
    this.cancelled = true;
  }

  /**
   * Comprueba que la carpeta local no contiene la copia del servidor de la carpeta remota: deja un archivo
   * de prueba en el servidor y mira si aparece aquí. Lanza SyncLoopError si aparece.
   * @param {Map<string, LocalEntry>} [scanned]  un recorrido local hecho después de dejar la prueba
   */
  async checkLoop(scanned) {
    const name = PROBE_PREFIX + crypto.randomBytes(8).toString("hex");
    await this.remote.put(this.rpath(name), Buffer.from("StorageWeb: loop check\n"), { ifNoneMatch: true });
    let found;
    try {
      const local = scanned || await this.local.scan();
      found = [...local.keys()].find((k) => k === name || k.endsWith(`/${name}`));
    } finally {
      await this.remote.remove(this.rpath(name)).catch(() => undefined);
    }
    if (found !== undefined) throw new SyncLoopError(found.slice(0, -name.length).replace(/\/$/, ""));
  }

  /** @param {string} path */
  rpath(path) {
    return `${this.root}/${path}`;
  }

  async ensureRemoteDir(path) {
    const dir = path.split("/").slice(0, -1).join("/");
    if (!dir || this.remoteDirs.has(dir)) return;
    await this.remote.mkdirs(this.rpath(dir));
    const parts = dir.split("/");
    for (let i = 1; i <= parts.length; i++) this.remoteDirs.add(parts.slice(0, i).join("/"));
  }

  /**
   * Sincronización completa. `confirmDeletes(n)` decide si se borran `n` archivos de golpe; si dice
   * que no, en vez de borrar se recuperan (se vuelve a bajar o a subir lo que falta).
   * `checkLoop`: antes, comprobar que la carpeta local no contiene la copia del servidor (ver SyncLoopError).
   * @param {{confirmDeletes?: (count: number) => Promise<boolean>, maxDeletes?: number, checkLoop?: boolean}} [options]
   */
  async run(options = {}) {
    const state = await this.store.load();
    if (options.checkLoop) await this.checkLoop();
    const local = await this.local.scan();
    for (const key of [...local.keys()]) if (key.split("/").pop().startsWith(PROBE_PREFIX)) local.delete(key);
    const remote = await this.remote.walk(this.root, (rel, isDir) => this.skip(rel, isDir));
    this.remoteDirs = new Set();
    for (const path of remote.keys()) {  // las carpetas de los archivos remotos ya existen: no hace falta crearlas
      const parts = path.split("/").slice(0, -1);
      for (let i = 1; i <= parts.length; i++) this.remoteDirs.add(parts.slice(0, i).join("/"));
    }
    const now = Date.now();
    for (const [path, s] of [...state]) if (s.hidden && now - s.hidden > HIDDEN_RETRY_MS) state.delete(path);
    let actions = plan(local, remote, state);
    // Lo que «desapareció» del servidor puede estar oculto para todos: entonces no se borra aquí
    for (const action of actions) {
      if (action.type === "deleteLocal" && this.remote.isHidden && await this.remote.isHidden(this.rpath(action.path))) {
        action.type = "hidden";
      }
    }
    const deletions = actions.filter((a) => a.type === "deleteLocal" || a.type === "deleteRemote");
    const maxDeletes = options.maxDeletes === undefined ? 10 : options.maxDeletes;
    if (deletions.length > maxDeletes && options.confirmDeletes && !(await options.confirmDeletes(deletions.length))) {
      actions = actions.map((a) => a.type === "deleteLocal" ? { ...a, type: "upload" }
        : a.type === "deleteRemote" ? { ...a, type: "download" } : a);
    }
    const summary = { uploaded: 0, downloaded: 0, deletedLocal: 0, deletedRemote: 0, hidden: 0,
      /** @type {{path: string, copy: string}[]} */ conflicts: [], /** @type {{path: string, error: string}[]} */ errors: [] };
    let done = 0, saved = Date.now();
    for (const action of actions) {
      if (this.cancelled) break;
      if (++done % SAVE_EVERY === 0 || Date.now() - saved > SAVE_EVERY_MS) {
        await this.store.save(state);
        saved = Date.now();
      }
      try {
        await this.apply(action, local, remote, state, summary);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        summary.errors.push({ path: action.path, error: message });
        this.log(`! ${action.type} ${action.path}: ${message}`);
        if (err instanceof DavError && (err.status === 0 || err.status === 401)) break;  // sin red o sin acceso
      }
    }
    await this.store.save(state);
    return summary;
  }

  /** @param {Action} action */
  async apply(action, local, remote, state, summary) {
    const { type, path } = action;
    const r = remote.get(path), s = state.get(path);
    if (type === "upload") {
      try {
        state.set(path, await this.upload(path, s ? s.etag : undefined, !!r));
        summary.uploaded++;
      } catch (err) {
        if (err instanceof DavError && err.hidden) {
          this.markHidden(path, local, state, summary);
          return;
        }
        // 412: el servidor tiene otra versión (cambió entre medias, o ya estaba aunque no saliera en el
        // listado): se compara con la de verdad en vez de dar error
        if (!(err instanceof DavError && err.status === 412)) throw err;
        const current = await this.remote.stat(this.rpath(path));
        if (!current || current.isDir) throw err;
        remote.set(path, current);
        await this.apply({ type: r ? "conflict" : "compare", path }, local, remote, state, summary);
      }
    } else if (type === "download") {
      state.set(path, await this.download(path, r.etag));
      summary.downloaded++;
    } else if (type === "deleteLocal") {
      await this.local.remove(path);
      state.delete(path);
      summary.deletedLocal++;
      this.log(`✕ ${path} (local)`);
    } else if (type === "deleteRemote") {
      await this.remote.remove(this.rpath(path), { ifMatch: s.etag });
      state.delete(path);
      summary.deletedRemote++;
      this.log(`✕ ${path} (server)`);
    } else if (type === "forget") {
      state.delete(path);
    } else if (type === "hidden") {
      this.markHidden(path, local, state, summary);
    } else if (type === "compare") {
      const theirs = await this.remote.get(this.rpath(path));
      const mine = await this.local.read(path);
      if (Buffer.compare(theirs, mine) === 0) {
        const l = /** @type {LocalEntry} */ (await this.local.stat(path));
        state.set(path, { size: l.size, mtime: l.mtime, etag: r.etag });
      } else {
        await this.conflict(path, r.etag, state, summary, theirs);
      }
    } else if (type === "conflict") {
      await this.conflict(path, r.etag, state, summary);
    }
  }

  /** El servidor oculta esta ruta para todos: se queda solo aquí (ni se sube ni se borra). */
  markHidden(path, local, state, summary) {
    const l = local.get(path) || { size: 0, mtime: 0 };
    state.set(path, { size: l.size, mtime: l.mtime, etag: "", hidden: Date.now() });
    if (summary) summary.hidden++;
    this.log(`‒ ${path} (hidden on the server: kept only here)`);
  }

  /** Sube el archivo; con `etag`, solo si el servidor sigue teniendo esa versión. */
  async upload(path, etag, exists) {
    const data = await this.local.read(path);
    const before = await this.local.stat(path);
    await this.ensureRemoteDir(path);
    const newEtag = await this.remote.put(this.rpath(path), data,
      etag && exists ? { ifMatch: etag } : exists ? {} : { ifNoneMatch: true });
    this.log(`↑ ${path}`);
    const l = before || { size: data.length, mtime: 0 };
    return { size: l.size, mtime: l.mtime, etag: newEtag };
  }

  async download(path, etag) {
    const data = await this.remote.get(this.rpath(path));
    const l = await this.local.write(path, data);
    this.log(`↓ ${path}`);
    return { size: l.size, mtime: l.mtime, etag };
  }

  /** Conflicto: la local pasa a «(conflicto …)» y se sube; la del servidor se queda con el nombre. */
  async conflict(path, etag, state, summary, remoteData) {
    const copy = conflictName(path, this.conflictLabel);
    await this.local.rename(path, copy);
    const data = remoteData || await this.remote.get(this.rpath(path));
    const l = await this.local.write(path, data);
    state.set(path, { size: l.size, mtime: l.mtime, etag });
    state.set(copy, await this.upload(copy, undefined, false));
    summary.conflicts.push({ path, copy });
    this.log(`⚠ ${path} → ${copy}`);
  }

  /**
   * Sube o borra en el servidor los archivos que acaban de cambiar aquí (al guardar), sin recorrer todo.
   * Devuelve false si hace falta una sincronización completa (el servidor cambió entre medias).
   * @param {string[]} paths
   */
  async push(paths) {
    const state = await this.store.load();
    let clean = true;
    for (const path of paths) {
      if (this.cancelled) break;
      if (this.skip(path)) continue;
      const l = await this.local.stat(path), s = state.get(path);
      if (s && s.hidden) continue;  // oculto en el servidor
      try {
        if (l && s && l.size === s.size && l.mtime === s.mtime) continue;  // sin cambios (p. ej. lo bajamos nosotros)
        if (l) {
          state.set(path, await this.upload(path, s && s.etag, !!s));
        } else if (s) {
          await this.remote.remove(this.rpath(path), { ifMatch: s.etag });
          state.delete(path);
          this.log(`✕ ${path} (server)`);
        }
      } catch (err) {
        if (err instanceof DavError && err.hidden && l) this.markHidden(path, new Map([[path, l]]), state);
        else if (err instanceof DavError && err.status === 412) clean = false;  // cambió en el servidor: conflicto
        else throw err;
      }
    }
    await this.store.save(state);
    return clean;
  }
}

module.exports = { SyncEngine, SyncLoopError, conflictName, plan };

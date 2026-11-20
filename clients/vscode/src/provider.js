// @ts-check
"use strict";
/**
 * `storageweb://<id del servidor>/<carpeta>/<archivo>`: los archivos del servidor en VS Code (abrir, guardar,
 * crear, renombrar, borrar y copiar, también desde el explorador si se añade la carpeta al espacio de
 * trabajo). Adapta remotefs.js a la API `FileSystemProvider` y avisa de los cambios hechos desde aquí y de los
 * que hagan otros en el servidor: VS Code pide vigilar (`watch`) cada archivo abierto y cada carpeta desplegada, y
 * cada `storageweb.refreshSeconds` se comprueban (una petición por cada uno, solo con la ventana activa). Si algo
 * cambió, VS Code recarga el editor (si no tiene cambios sin guardar; si los tiene, al guardar avisa del
 * conflicto) y refresca el explorador.
 */

const vscode = require("vscode");

const { RemoteFsError, parentOf } = require("./remotefs");

const t = vscode.l10n.t;
const SCHEME = "storageweb";

/** @param {string} server @param {string} path */
function remoteUri(server, path) {
  return vscode.Uri.from({ scheme: SCHEME, authority: server, path: "/" + path.split("/").filter(Boolean).join("/") });
}

/** @param {vscode.Uri} uri */
function pathOf(uri) {
  return uri.path.split("/").filter(Boolean).join("/");
}

class StorageWebFs {
  /** @param {import("./remotefs").RemoteFs} remote */
  constructor(remote) {
    this.remote = remote;
    /** @type {vscode.EventEmitter<vscode.FileChangeEvent[]>} */
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeFile = this.emitter.event;
    /** Lo vigilado; `last` es la última «firma» vista (null = aún no se sabe).
     * @type {Map<string, {uri: vscode.Uri, count: number, last: string | null}>} */
    this.watched = new Map();
    /** @type {ReturnType<typeof setTimeout> | null} */
    this.timer = null;
    this.polling = false;
    const win = vscode.window;
    // Al volver a la ventana, se comprueba enseguida (mientras no está activa no se pregunta al servidor)
    this.focusListener = win.onDidChangeWindowState
      ? win.onDidChangeWindowState((/** @type {{focused: boolean}} */ s) => { if (s.focused) this.poll(); })
      : null;
  }

  /** Segundos entre comprobaciones (0 = no se comprueba; como poco, 5). */
  refreshSeconds() {
    const value = vscode.workspace.getConfiguration("storageweb").get("refreshSeconds");
    if (typeof value !== "number" || value < 0) return 30;
    return value === 0 ? 0 : Math.max(value, 5);
  }

  /** VS Code pide vigilar un archivo abierto o una carpeta desplegada. @param {vscode.Uri} uri */
  watch(uri) {
    const key = uri.toString();
    const entry = this.watched.get(key) || { uri, count: 0, last: null };
    entry.count++;
    this.watched.set(key, entry);
    this.schedule();
    return new vscode.Disposable(() => {
      entry.count--;
      if (entry.count <= 0) this.watched.delete(key);
    });
  }

  schedule() {
    if (this.timer || !this.watched.size) return;
    const seconds = this.refreshSeconds();
    if (!seconds) return;
    this.timer = setTimeout(async () => {
      this.timer = null;
      const state = vscode.window.state;
      if (!state || state.focused) await this.poll();
      this.schedule();
    }, seconds * 1000);
    if (typeof this.timer.unref === "function") this.timer.unref();
  }

  /** Comprueba lo vigilado y avisa de lo que cambió en el servidor desde la vez anterior. */
  async poll() {
    if (this.polling) return;
    this.polling = true;
    try {
      /** @type {vscode.FileChangeEvent[]} */
      const events = [];
      for (const entry of [...this.watched.values()]) {
        const before = entry.last;
        let now;
        try {
          now = await this.signature(entry.uri);
        } catch (err) {
          if (!(err instanceof RemoteFsError) || err.code !== "FileNotFound") continue;  // sin red: la próxima vez
          now = "missing";
        }
        entry.last = now;
        if (before === null || before === now) continue;
        const type = now === "missing" ? vscode.FileChangeType.Deleted
          : before === "missing" ? vscode.FileChangeType.Created : vscode.FileChangeType.Changed;
        events.push({ type, uri: entry.uri });
      }
      if (events.length) this.emitter.fire(events);
    } finally {
      this.polling = false;
    }
  }

  /** La versión: fecha y tamaño de un archivo; nombres y tipos de lo que hay en una carpeta. @param {vscode.Uri} uri */
  async signature(uri) {
    const s = await this.remote.stat(uri.authority, uri.path);
    if (s.type !== "dir") return `file:${s.mtime}:${s.size}`;
    const items = await this.remote.readDirectory(uri.authority, uri.path);
    return "dir:" + items.map(([name, type]) => `${type}/${name}`).sort().join("|");
  }

  /** Lo cambiado desde aquí ya se avisó: la siguiente comprobación toma la versión nueva sin avisar otra vez.
   * @param {vscode.Uri} uri */
  rebase(uri) {
    for (const u of [uri, uri.with({ path: "/" + parentOf(pathOf(uri)) })]) {
      const entry = this.watched.get(u.toString());
      if (entry) entry.last = null;
    }
  }

  dispose() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.watched.clear();
    if (this.focusListener) this.focusListener.dispose();
  }

  /** @param {vscode.Uri} uri @param {unknown} err */
  error(uri, err) {
    if (!(err instanceof RemoteFsError)) return err;
    switch (err.code) {
      case "FileNotFound": return vscode.FileSystemError.FileNotFound(uri);
      case "FileExists": return vscode.FileSystemError.FileExists(uri);
      case "FileNotADirectory": return vscode.FileSystemError.FileNotADirectory(uri);
      case "FileIsADirectory": return vscode.FileSystemError.FileIsADirectory(uri);
      case "NoPermissions":
        return vscode.FileSystemError.NoPermissions(err.message.startsWith("The server rejected")
          ? t("The server rejected the user or the token.") : uri);
      case "Unavailable": return vscode.FileSystemError.Unavailable(t("Cannot connect to the server: {0}", err.message));
      case "Conflict":
        return new vscode.FileSystemError(
          t("«{0}» changed on the server while saving: it was not overwritten. Reopen it to see the new version.",
            uri.path.split("/").pop() || ""));
      default: return new vscode.FileSystemError(err.message);
    }
  }

  /** @template T @param {vscode.Uri} uri @param {() => Promise<T>} job @returns {Promise<T>} */
  async call(uri, job) {
    try {
      return await job();
    } catch (err) {
      throw this.error(uri, err);
    }
  }

  /** @param {vscode.Uri} uri @param {vscode.FileChangeType} type */
  changed(uri, type) {
    this.rebase(uri);
    const parent = uri.with({ path: "/" + parentOf(pathOf(uri)) });
    this.emitter.fire([{ type, uri }, { type: vscode.FileChangeType.Changed, uri: parent }]);
  }

  /** @param {vscode.Uri} uri @returns {Promise<vscode.FileStat>} */
  async stat(uri) {
    const s = await this.call(uri, () => this.remote.stat(uri.authority, uri.path));
    return { type: s.type === "dir" ? vscode.FileType.Directory : vscode.FileType.File, size: s.size,
      mtime: s.mtime, ctime: s.mtime };
  }

  /** @param {vscode.Uri} uri @returns {Promise<[string, vscode.FileType][]>} */
  async readDirectory(uri) {
    const items = await this.call(uri, () => this.remote.readDirectory(uri.authority, uri.path));
    return items.map(([name, type]) => [name, type === "dir" ? vscode.FileType.Directory : vscode.FileType.File]);
  }

  /** @param {vscode.Uri} uri */
  async readFile(uri) {
    return new Uint8Array(await this.call(uri, () => this.remote.readFile(uri.authority, uri.path)));
  }

  /** @param {vscode.Uri} uri @param {Uint8Array} content @param {{create: boolean, overwrite: boolean}} options */
  async writeFile(uri, content, options) {
    const created = await this.call(uri, () => this.remote.writeFile(uri.authority, uri.path, content, options));
    this.changed(uri, created ? vscode.FileChangeType.Created : vscode.FileChangeType.Changed);
  }

  /** @param {vscode.Uri} uri */
  async createDirectory(uri) {
    await this.call(uri, () => this.remote.createDirectory(uri.authority, uri.path));
    this.changed(uri, vscode.FileChangeType.Created);
  }

  /** @param {vscode.Uri} uri */
  async delete(uri) {
    await this.call(uri, () => this.remote.delete(uri.authority, uri.path));
    this.changed(uri, vscode.FileChangeType.Deleted);
  }

  /** @param {vscode.Uri} from @param {vscode.Uri} to @param {{overwrite: boolean}} options */
  async rename(from, to, options) {
    if (from.authority !== to.authority) throw vscode.FileSystemError.NoPermissions(to);
    await this.call(from, () => this.remote.rename(from.authority, from.path, to.path, options));
    this.changed(from, vscode.FileChangeType.Deleted);
    this.changed(to, vscode.FileChangeType.Created);
  }

  /** Copia en el mismo servidor (la hace el servidor). @param {vscode.Uri} from @param {vscode.Uri} to @param {{overwrite: boolean}} options */
  async copy(from, to, options) {
    if (from.authority !== to.authority) throw vscode.FileSystemError.NoPermissions(to);
    await this.call(from, () => this.remote.copy(from.authority, from.path, to.path, options));
    this.changed(to, vscode.FileChangeType.Created);
  }
}

module.exports = { StorageWebFs, SCHEME, remoteUri, pathOf };

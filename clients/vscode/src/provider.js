// @ts-check
"use strict";
/**
 * `storageweb://<id del servidor>/<carpeta>/<archivo>`: los archivos del servidor en VS Code (abrir, guardar,
 * crear, renombrar, borrar y copiar, también desde el explorador si se añade la carpeta al espacio de
 * trabajo). Adapta remotefs.js a la API `FileSystemProvider` y avisa de los cambios hechos desde aquí.
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
  }

  /** Los cambios del servidor llegan al refrescar o al volver a abrir: no hay avisos en vivo. */
  watch() {
    return new vscode.Disposable(() => undefined);
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

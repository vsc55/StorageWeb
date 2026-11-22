// @ts-check
"use strict";
/**
 * Los paneles de la barra lateral de StorageWeb:
 *
 * - **Servidores**: cada servidor con sus carpetas (la personal y las compartidas) para navegar; las
 *   acciones (subir, bajar, renombrar, sincronizar con una carpeta local…) están en el menú contextual,
 *   que elige por `contextValue` (server, root, folder, file).
 * - **Sincronización**: las carpetas de esta ventana sincronizadas, con su estado.
 */

const vscode = require("vscode");

const { describe, isRejected, needsToken } = require("./messages");
const { remoteUri } = require("./provider");
const { hostOf } = require("./servers");

const t = vscode.l10n.t;

/**
 * @typedef {import("./servers").ServerProfile} ServerProfile
 * @typedef {{kind: "server", profile: ServerProfile}} ServerNode
 * @typedef {{kind: "entry", profile: ServerProfile, path: string, name: string, label: string, isDir: boolean,
 *            size: number, mtime: number}} EntryNode
 * @typedef {{kind: "message", id: string, text: string, icon: string, command?: vscode.Command}} MessageNode
 * @typedef {ServerNode | EntryNode | MessageNode} Node
 */

/** @param {number} bytes */
function humanSize(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes, i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${i ? value.toFixed(value < 10 ? 1 : 0) : value} ${units[i]}`;
}

class ServersTree {
  /**
   * @param {import("./servers").ServerStore} store
   * @param {import("./remotefs").RemoteFs} remote
   */
  constructor(store, remote) {
    this.store = store;
    this.remote = remote;
    /** @type {vscode.EventEmitter<Node | undefined>} */
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
    /** @type {Map<string, Node>} las carpetas mostradas, para refrescar solo la que cambió */
    this.nodes = new Map();
  }

  /** Todo (sin caché) o solo un nodo. @param {Node} [node] */
  refresh(node) {
    if (!node) {
      this.remote.forget();
      this.nodes.clear();
    }
    this.emitter.fire(node);
  }

  /**
   * Cambiaron estos archivos o carpetas (desde esta ventana): se refresca cada carpeta afectada que se esté
   * mostrando, una vez: la carpeta que cambió o, si se creó o se borró algo, la que lo contiene.
   * @param {readonly vscode.FileChangeEvent[]} events
   */
  changed(events) {
    const nodes = new Set();
    for (const { type, uri } of events) {
      const parts = uri.path.split("/").filter(Boolean);
      const key = (/** @type {string[]} */ p) => (p.length ? `${uri.authority}:${p.join("/")}` : `server:${uri.authority}`);
      const node = (type === vscode.FileChangeType.Changed && this.nodes.get(key(parts)))
        || this.nodes.get(key(parts.slice(0, -1)));
      if (node) nodes.add(node);
    }
    for (const node of nodes) this.emitter.fire(node);
  }

  /** @param {Node} node @returns {vscode.TreeItem} */
  getTreeItem(node) {
    if (node.kind === "server") {
      const item = new vscode.TreeItem(this.store.title(node.profile), vscode.TreeItemCollapsibleState.Collapsed);
      item.id = `server:${node.profile.id}`;
      item.description = node.profile.label ? `${node.profile.username} · ${hostOf(node.profile.url)}`
        : node.profile.username;
      item.tooltip = `${node.profile.url}\n${t("User: {0}", node.profile.username)}`;
      item.iconPath = new vscode.ThemeIcon("server");
      item.contextValue = "server";
      return item;
    }
    if (node.kind === "message") {
      const item = new vscode.TreeItem(node.text, vscode.TreeItemCollapsibleState.None);
      item.id = node.id;
      item.iconPath = new vscode.ThemeIcon(node.icon);
      item.command = node.command;
      item.tooltip = node.text;
      item.contextValue = "message";
      return item;
    }
    const top = !node.path.includes("/");
    const uri = remoteUri(node.profile.id, node.path);
    const item = new vscode.TreeItem(top ? node.label || node.name : node.name,
      node.isDir ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None);
    item.id = `${node.profile.id}:${node.path}`;
    item.resourceUri = uri;
    const when = node.mtime ? new Date(node.mtime).toLocaleString() : "";
    if (top) {
      item.iconPath = new vscode.ThemeIcon(node.name === "home" ? "home" : "folder-library");
      item.description = node.name === "home" ? t("your personal folder") : t("shared");
      item.tooltip = `${node.label || node.name}\n${node.path}`;
      item.contextValue = "root";
    } else if (node.isDir) {
      item.iconPath = vscode.ThemeIcon.Folder;
      item.tooltip = node.path;
      item.contextValue = "folder";
    } else {
      item.iconPath = vscode.ThemeIcon.File;
      item.description = humanSize(node.size);
      item.tooltip = `${node.path}\n${humanSize(node.size)}${when ? ` · ${when}` : ""}`;
      item.contextValue = "file";
      item.command = { command: "vscode.open", title: t("Open"), arguments: [uri] };
    }
    return item;
  }

  /** @param {Node} [node] @returns {Promise<Node[]>} */
  async getChildren(node) {
    if (!node) return this.store.list().map((profile) => ({ kind: "server", profile }));
    if (node.kind === "message") return [];
    const profile = node.profile;
    const path = node.kind === "server" ? "" : node.path;
    this.nodes.set(node.kind === "server" ? `server:${profile.id}` : `${profile.id}:${path}`, node);
    if (!(await this.store.token(profile))) {
      return [{ kind: "message", id: `${profile.id}:!token`, icon: "key",
        text: t("No token on this computer: set it"),
        command: { command: "storageweb.setToken", title: t("Set token…"), arguments: [{ kind: "server", profile }] } }];
    }
    let entries;
    try {
      entries = await this.remote.list(profile.id, path);
    } catch (err) {
      // Lo que se arregla con otro token lleva a ponerlo; lo demás (cuenta desactivada, IP bloqueada,
      // mantenimiento, sin red, sin acceso…), a reintentar
      const fix = needsToken(err);
      return [{ kind: "message", id: `${profile.id}:${path}:!error`, icon: fix ? "key" : "warning",
        text: describe(err),
        command: fix
          ? { command: "storageweb.setToken", title: t("Set token…"), arguments: [{ kind: "server", profile }] }
          : { command: "storageweb.refreshNode", title: t("Retry"), arguments: [node] } }];
    }
    if (!entries.length && path) {
      return [{ kind: "message", id: `${profile.id}:${path}:!empty`, icon: "blank", text: t("(empty)") }];
    }
    return entries
      .sort((a, b) => (a.isDir === b.isDir ? a.name.localeCompare(b.name) : a.isDir ? -1 : 1))
      .map((e) => ({ kind: "entry", profile, path: e.path, name: e.name, label: e.label, isDir: e.isDir,
        size: e.size, mtime: e.mtime }));
  }
}

/**
 * @typedef {{folder: vscode.WorkspaceFolder, server: string, username: string, remoteFolder: string,
 *            state: "busy" | "error" | "ok" | "waiting" | "notoken" | "paused", error?: string, lastSync?: Date}} SyncInfo
 * @typedef {{kind: "sync", info: SyncInfo}} SyncNode
 */

class SyncTree {
  /** @param {() => SyncInfo[]} items */
  constructor(items) {
    this.items = items;
    /** @type {vscode.EventEmitter<SyncNode | undefined>} */
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
  }

  refresh() {
    this.emitter.fire(undefined);
  }

  /** @param {SyncNode} node */
  getTreeItem(node) {
    const { info } = node;
    const item = new vscode.TreeItem(info.folder.name, vscode.TreeItemCollapsibleState.None);
    item.id = `sync:${info.folder.uri}`;
    item.description = `${hostOf(info.server)} · ${info.remoteFolder}`;
    const state = {
      busy: t("synchronizing…"),
      error: t("error: {0}", info.error || ""),
      ok: info.lastSync ? t("synchronized at {0}", info.lastSync.toLocaleTimeString()) : t("not synchronized yet"),
      waiting: t("not synchronized yet"),
      notoken: t("there is no token on this computer"),
      paused: t("paused"),
    }[info.state];
    item.tooltip = `${info.folder.uri.fsPath}\n⇄ ${info.server}/f/${info.remoteFolder}\n${t("User: {0}", info.username)}\n${state}`;
    item.iconPath = {
      busy: new vscode.ThemeIcon("sync~spin"),
      error: new vscode.ThemeIcon("warning", new vscode.ThemeColor("problemsWarningIcon.foreground")),
      ok: new vscode.ThemeIcon("pass", new vscode.ThemeColor("testing.iconPassed")),
      waiting: new vscode.ThemeIcon("clock"),
      notoken: new vscode.ThemeIcon("key"),
      paused: new vscode.ThemeIcon("debug-pause"),
    }[info.state];
    if (info.state === "paused") item.description = `${t("paused")} · ${item.description}`;
    item.contextValue = info.state === "notoken" ? "sync-notoken" : info.state === "paused" ? "sync-paused" : "sync";
    return item;
  }

  /** @param {SyncNode} [node] @returns {SyncNode[]} */
  getChildren(node) {
    return node ? [] : this.items().map((info) => ({ kind: "sync", info }));
  }
}

module.exports = { ServersTree, SyncTree, describe, humanSize, isRejected };

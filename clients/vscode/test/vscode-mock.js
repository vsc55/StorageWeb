// Un módulo `vscode` mínimo para cargar la extensión en Node (sin VS Code). No es un test.
"use strict";
const Module = require("node:module");
const path = require("node:path");

function format(text, args) {
  return text.replace(/\{(\d+)\}/g, (_m, i) => String(args[Number(i)]));
}

class Uri {
  constructor(scheme, authority, uriPath, query = "") {
    this.scheme = scheme;
    this.authority = authority;
    this.path = uriPath || "/";
    this.query = query;
  }
  static from(c) { return new Uri(c.scheme, c.authority || "", c.path); }
  static file(p) { return new Uri("file", "", path.resolve(p).split(path.sep).join("/")); }
  static parse(s) {
    const u = new URL(s);
    return new Uri(u.protocol.slice(0, -1), u.host, decodeURIComponent(u.pathname), u.search.slice(1));
  }
  static joinPath(base, ...parts) { return base.with({ path: path.posix.join(base.path, ...parts) }); }
  get fsPath() { return this.scheme === "file" ? path.resolve(this.path) : this.path; }
  with(c) { return new Uri(c.scheme || this.scheme, c.authority === undefined ? this.authority : c.authority, c.path || this.path); }
  toString(skipEncoding) {
    const p = skipEncoding ? this.path : this.path.split("/").map(encodeURIComponent).join("/");
    return `${this.scheme}://${this.authority}${p}${this.query ? `?${this.query}` : ""}`;
  }
}

class EventEmitter {
  constructor() {
    this.listeners = [];
    this.event = (fn) => {
      this.listeners.push(fn);
      return { dispose: () => { this.listeners = this.listeners.filter((l) => l !== fn); } };
    };
  }
  fire(e) { for (const l of this.listeners) l(e); }
  dispose() { this.listeners = []; }
}

class Disposable {
  constructor(fn) { this.fn = fn; }
  dispose() { if (this.fn) this.fn(); }
}

class ThemeIcon {
  constructor(id, color) { this.id = id; this.color = color; }
}
ThemeIcon.Folder = new ThemeIcon("folder");
ThemeIcon.File = new ThemeIcon("file");

class FileSystemError extends Error {
  constructor(messageOrUri) {
    super(String(messageOrUri === undefined ? "" : messageOrUri));
    this.code = "Unknown";
  }
}
for (const code of ["FileNotFound", "FileExists", "FileNotADirectory", "FileIsADirectory", "NoPermissions", "Unavailable"]) {
  FileSystemError[code] = (m) => Object.assign(new FileSystemError(m), { code });
}

/** El mock y lo que se registró en él (comandos, sistemas de archivos, mensajes). */
function createVscode() {
  const registered = { commands: new Map(), fileSystems: new Map(), messages: [], trees: new Map(), uriHandler: null };
  const disposable = () => new Disposable();
  const message = (kind) => (text, ...rest) => {
    registered.messages.push({ kind, text, rest });
    return Promise.resolve(undefined);
  };
  const vscode = {
    Uri, EventEmitter, Disposable, ThemeIcon, FileSystemError,
    ThemeColor: class { constructor(id) { this.id = id; } },
    TreeItem: class { constructor(label, collapsibleState) { this.label = label; this.collapsibleState = collapsibleState; } },
    TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
    FileType: { Unknown: 0, File: 1, Directory: 2, SymbolicLink: 64 },
    FileChangeType: { Changed: 1, Created: 2, Deleted: 3 },
    StatusBarAlignment: { Left: 1, Right: 2 },
    ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
    ProgressLocation: { SourceControl: 1, Window: 10, Notification: 15 },
    UIKind: { Desktop: 1, Web: 2 },
    RelativePattern: class { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
    l10n: { t: (text, ...args) => format(text, args) },
    env: { openExternal: async () => true, uriScheme: "vscode", asExternalUri: async (uri) => uri, uiKind: 1, language: "en" },
    authentication: {
      // Sin cuenta: como si la persona cancelara el selector de cuentas (los tests lo cambian)
      getSession: async () => { throw new Error("User did not consent to login."); },
    },
    commands: {
      registerCommand: (id, fn) => {
        if (registered.commands.has(id)) throw new Error(`command ${id} registered twice`);
        registered.commands.set(id, fn);
        return disposable();
      },
      executeCommand: async (id, ...args) => (registered.commands.has(id) ? registered.commands.get(id)(...args) : undefined),
    },
    window: {
      createOutputChannel: () => ({ appendLine: () => undefined, show: () => undefined, dispose: () => undefined }),
      createStatusBarItem: () => ({ show: () => undefined, hide: () => undefined, dispose: () => undefined }),
      createTreeView: (id, options) => {
        registered.trees.set(id, options.treeDataProvider);
        return disposable();
      },
      showInformationMessage: message("info"),
      showWarningMessage: message("warning"),
      showErrorMessage: message("error"),
      showInputBox: async () => undefined,
      showQuickPick: async () => undefined,
      showOpenDialog: async () => undefined,
      showSaveDialog: async () => undefined,
      withProgress: async (_o, task) => task({ report: () => undefined },
        { isCancellationRequested: false, onCancellationRequested: () => ({ dispose: () => undefined }) }),
      registerUriHandler: (handler) => {
        registered.uriHandler = handler;
        return disposable();
      },
      activeTextEditor: undefined,
    },
    workspace: {
      workspaceFolders: undefined,
      getConfiguration: () => ({ get: () => undefined, update: async () => undefined }),
      getWorkspaceFolder: () => undefined,
      registerFileSystemProvider: (scheme, provider) => {
        registered.fileSystems.set(scheme, provider);
        return disposable();
      },
      onDidChangeWorkspaceFolders: disposable,
      onDidChangeConfiguration: disposable,
      createFileSystemWatcher: () => ({ onDidCreate: disposable, onDidChange: disposable, onDidDelete: disposable, dispose: () => undefined }),
      updateWorkspaceFolders: () => true,
      fs: {},
    },
  };
  return { vscode, registered };
}

/** Carga los módulos de la extensión con este `vscode` (y limpia la caché para no mezclar mocks). */
function withVscode(vscode, load) {
  const original = Module._load;
  const src = path.join(__dirname, "..", "src") + path.sep;
  for (const key of Object.keys(require.cache)) if (key.startsWith(src)) delete require.cache[key];
  Module._load = function (request, ...rest) {
    if (request === "vscode") return vscode;
    return original.call(this, request, ...rest);
  };
  try {
    return load();
  } finally {
    Module._load = original;
  }
}

/** Un `ExtensionContext` en memoria. */
function createContext() {
  const state = new Map(), secrets = new Map(), wsState = new Map();
  return {
    extension: { id: "storageweb.storageweb-sync" },
    subscriptions: [],
    globalStorageUri: Uri.file(path.join(require("node:os").tmpdir(), "sw-vscode-test")),
    workspaceState: { get: (k) => wsState.get(k), update: async (k, v) => { wsState.set(k, v); }, keys: () => [...wsState.keys()] },
    globalState: { get: (k) => state.get(k), update: async (k, v) => { state.set(k, v); }, keys: () => [...state.keys()] },
    secrets: { get: async (k) => secrets.get(k), store: async (k, v) => { secrets.set(k, v); }, delete: async (k) => { secrets.delete(k); } },
  };
}

module.exports = { createVscode, withVscode, createContext };

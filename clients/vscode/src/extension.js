// @ts-check
"use strict";
/**
 * StorageWeb para VS Code.
 *
 * - **Sincronizar** una carpeta del espacio de trabajo con una de StorageWeb (por WebDAV, con el usuario y
 *   un token de API): al guardar, crear, renombrar o borrar, sube o borra solo lo cambiado (con If-Match:
 *   si cambió en el servidor entre medias, no se pisa y se hace una sincronización completa); cada
 *   `storageweb.pollSeconds`, una sincronización completa; los conflictos guardan las dos versiones.
 * - **Panel lateral** con varios servidores para navegar por sus carpetas, abrir y guardar archivos
 *   directamente en el servidor (`storageweb://`, provider.js), subir, bajar, renombrar, borrar y elegir
 *   qué sincronizar.
 *
 * La lógica está en sync.js, remotefs.js y servers.js (sin VS Code); aquí solo comandos, avisos y vigilancia.
 */

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const vscode = require("vscode");

const { ConnectError, exchange, parseCallback, startRequest } = require("./connect");
const { DavClient, DavError } = require("./dav");
const { DEFAULT_EXCLUDES, excluder, ignorePatterns } = require("./glob");
const { LocalFs } = require("./localfs");
const { SCHEME, StorageWebFs, remoteUri } = require("./provider");
const { RemoteFs, RemoteFsError, parentOf } = require("./remotefs");
const { ServerStore, hostOf, normalizeUrl, secretKey } = require("./servers");
const { SyncEngine, SyncLoopError } = require("./sync");
const { ServersTree, SyncTree, describe } = require("./views");

const t = vscode.l10n.t;
const SECTION = "storageweb";
const PENDING = "storageweb.pendingLinks";
const SIGN_IN_MINUTES = 5;
const IGNORE_FILE = ".storagewebignore";
const PAUSED = "storageweb.paused";

/** @type {vscode.OutputChannel} */
let output;
/** @type {vscode.StatusBarItem} */
let status;
/** @type {vscode.ExtensionContext} */
let ctx;
/** @type {ServerStore} */
let store;
/** @type {RemoteFs} */
let remote;
/** @type {ServersTree} */
let serversTree;
/** @type {SyncTree} */
let syncTree;
/** @type {Map<string, FolderSync>} carpeta (uri) → su sincronización */
const running = new Map();
/** @type {Map<string, number>} última orden de arranque por carpeta (guardar la configuración la repite) */
const starts = new Map();
/** @type {Map<string, {key: string, client: DavClient}>} servidor (id) → su cliente WebDAV */
const clients = new Map();
/**
 * Inicios de sesión en el navegador esperando la vuelta (state → lo necesario para canjearla).
 * @type {Map<string, {server: string, verifier: string, done: (result: {code?: string, error?: string}) => void}>}
 */
const signIns = new Map();

function log(message) {
  output.appendLine(`[${new Date().toLocaleTimeString()}] ${message}`);
}

/** @param {vscode.WorkspaceFolder} folder */
function binding(folder) {
  if (folder.uri.scheme !== "file") return null;  // una carpeta del servidor añadida al espacio de trabajo
  const cfg = vscode.workspace.getConfiguration(SECTION, folder.uri);
  const server = (cfg.get("server") || "").toString().replace(/\/+$/, "");
  const username = (cfg.get("username") || "").toString();
  const remoteFolder = (cfg.get("remoteFolder") || "").toString().replace(/^\/+|\/+$/g, "");
  return server && username && remoteFolder ? { server, username, remoteFolder } : null;
}

/** @param {unknown} err */
function showError(err) {
  vscode.window.showErrorMessage(t("StorageWeb: {0}", describe(err)));
}

// --------------------------------------------------------------------------- servidores

/** @param {import("./servers").ServerProfile} profile @returns {Promise<DavClient | undefined>} */
async function clientFor(profile) {
  const token = await store.token(profile);
  if (!token) return undefined;
  const key = `${profile.url}|${profile.username}|${token}`;
  const cached = clients.get(profile.id);
  if (cached && cached.key === key) return cached.client;
  const client = new DavClient(profile.url, profile.username, token);
  clients.set(profile.id, { key, client });
  return client;
}

/** Comprueba la dirección, el usuario y el token (lista las carpetas de arriba). @returns {Promise<boolean>} */
async function checkAccess(/** @type {DavClient} */ client) {
  try {
    await client.roots();
    return true;
  } catch (err) {
    showError(err);
    return false;
  }
}

/** Pide el token (con un enlace para crearlo). @param {string} url @param {string} title */
async function askToken(url, title) {
  const token = await vscode.window.showInputBox({
    title, password: true, ignoreFocusOut: true,
    prompt: t("API token (sw_…). Create it in StorageWeb → My profile → API tokens, with read and write scope."),
    validateInput: (v) => (v.trim().startsWith("sw_") ? null : t("Tokens start with sw_")),
  });
  if (!token) {
    const create = t("Create a token");
    const open = await vscode.window.showInformationMessage(t("You need an API token of StorageWeb."), create);
    if (open === create) vscode.env.openExternal(vscode.Uri.parse(`${url}/profile#tokens`));
    return undefined;
  }
  return token.trim();
}

/**
 * Iniciar sesión en el navegador (la web de StorageWeb, también con Microsoft) y recibir un token para este
 * equipo. @param {string} url @returns {Promise<{username: string, token: string} | undefined>}
 */
async function signInWithBrowser(url) {
  const callback = await vscode.env.asExternalUri(
    vscode.Uri.parse(`${vscode.env.uriScheme}://${ctx.extension.id}/auth`));
  const request = startRequest(url, callback.toString(true), os.hostname());
  /** @type {Promise<{code?: string, error?: string}>} */
  const answer = new Promise((resolve) => {
    signIns.set(request.state, { server: url, verifier: request.verifier, done: resolve });
  });
  let timer;
  try {
    if (!(await vscode.env.openExternal(vscode.Uri.parse(request.url, true)))) return undefined;
    const result = await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification, cancellable: true,
      title: t("StorageWeb: waiting for the sign-in in the browser…"),
    }, (_progress, cancel) => Promise.race([
      answer,
      new Promise((resolve) => cancel.onCancellationRequested(() => resolve({ error: "cancelled" }))),
      new Promise((resolve) => { timer = setTimeout(() => resolve({ error: "timeout" }), SIGN_IN_MINUTES * 60000); }),
    ]));
    if (result.error === "cancelled") return undefined;
    if (result.error === "timeout") throw new Error(t("The sign-in in the browser was not completed in {0} minutes.", SIGN_IN_MINUTES));
    if (result.error) throw new Error(t("Access was not granted in the browser."));
    const got = await exchange(url, result.code || "", request.verifier);
    log(t("Signed in from the browser as {0}: token «{1}»", got.username, got.name));
    return { username: got.username, token: got.token };
  } catch (err) {
    showError(err instanceof ConnectError && err.code === "unsupported"
      ? new Error(t("This StorageWeb does not support signing in from the browser yet: use a user name and an API token."))
      : err);
    return undefined;
  } finally {
    clearTimeout(timer);
    signIns.delete(request.state);
  }
}

/** La vuelta del navegador: vscode://storageweb.storageweb-sync/auth?code=…&state=… @param {vscode.Uri} uri */
function handleUri(uri) {
  if (uri.path !== "/auth") return;
  const { code, state, error } = parseCallback(uri.query);
  const pending = signIns.get(state);
  if (!pending) {
    vscode.window.showWarningMessage(t("StorageWeb: this sign-in is no longer pending. Start it again from VS Code."));
    return;
  }
  pending.done(error ? { error } : { code });
}

/**
 * Cómo conseguir las credenciales: iniciando sesión en el navegador o con usuario y token a mano.
 * `username`: el de un servidor ya añadido (no se pregunta y el del navegador tiene que coincidir).
 * @param {string} url @param {string} title @param {string} [username]
 * @returns {Promise<{username: string, token: string} | undefined>}
 */
async function askCredentials(url, title, username) {
  const choice = await vscode.window.showQuickPick([
    { label: `$(globe) ${t("Sign in with the browser")}`, method: "browser",
      detail: t("Uses the sign-in of StorageWeb (also Microsoft / Entra ID). Creates a token for this computer.") },
    { label: `$(key) ${t("User name and API token")}`, method: "token",
      detail: t("Paste a token created in StorageWeb → My profile → API tokens.") },
  ], { title, placeHolder: t("How do you want to sign in?"), ignoreFocusOut: true });
  if (!choice) return undefined;
  if (choice.method === "browser") {
    const got = await signInWithBrowser(url);
    if (got && username && got.username.toLowerCase() !== username.toLowerCase()) {
      showError(new Error(t("You signed in as «{0}», but this server is set up for «{1}». Add it as another server instead.",
        got.username, username)));
      return undefined;
    }
    return got;
  }
  const user = username || (await vscode.window.showInputBox({ title, prompt: t("User name in StorageWeb"),
    ignoreFocusOut: true }) || "").trim();
  if (!user) return undefined;
  const token = await askToken(url, title);
  return token ? { username: user, token } : undefined;
}

/** Lo que se tocó de un servidor: se olvida su cliente y su caché y se refrescan los paneles. @param {string} [id] */
function serverChanged(id) {
  if (id) {
    clients.delete(id);
    remote.forget(id);
  }
  serversTree.refresh();
}

async function addServerCommand() {
  const title = t("StorageWeb: add server");
  const url = await vscode.window.showInputBox({
    title, prompt: t("Address of StorageWeb"), value: "https://", ignoreFocusOut: true,
    validateInput: (v) => (normalizeUrl(v) ? null : t("For example https://files.company.com")),
  });
  if (!url) return undefined;
  const cleanUrl = /** @type {string} */ (normalizeUrl(url));
  const credentials = await askCredentials(cleanUrl, title);
  if (!credentials) return undefined;
  const { username, token } = credentials;
  if (!(await checkAccess(new DavClient(cleanUrl, username, token)))) return undefined;
  const profile = await store.add({ url: cleanUrl, username }, token);
  serverChanged(profile.id);
  log(t("Server added: {0} ({1})", cleanUrl, username));
  return profile;
}

/** El servidor de un nodo del panel o, desde la paleta, el que se elija. */
async function profileArg(/** @type {any} */ node, allowAdd = false) {
  if (node && node.profile) return store.get(node.profile.id) || node.profile;
  return pickProfile(allowAdd);
}

async function pickProfile(allowAdd = false) {
  const all = store.list();
  if (!all.length) {
    if (allowAdd) return addServerCommand();
    vscode.window.showInformationMessage(t("Add a StorageWeb server first."), t("Add server…"))
      .then((c) => c && vscode.commands.executeCommand("storageweb.addServer"));
    return undefined;
  }
  /** @type {(vscode.QuickPickItem & {id?: string})[]} */
  const items = all.map((p) => ({ label: `$(server) ${store.title(p)}`, description: p.username, detail: p.url, id: p.id }));
  if (allowAdd) items.push({ label: `$(add) ${t("Add server…")}` });
  const choice = await vscode.window.showQuickPick(items, { placeHolder: t("StorageWeb server"), ignoreFocusOut: true });
  if (!choice) return undefined;
  return choice.id ? store.get(choice.id) : addServerCommand();
}

/** Las carpetas de esta ventana sincronizadas con ese servidor. @param {import("./servers").ServerProfile} profile */
function foldersOf(profile) {
  return (vscode.workspace.workspaceFolders || []).filter((f) => {
    const bind = binding(f);
    return bind && normalizeUrl(bind.server) === profile.url && bind.username.toLowerCase() === profile.username.toLowerCase();
  });
}

async function setTokenCommand(/** @type {any} */ node) {
  const profile = await profileArg(node);
  if (!profile) return;
  const credentials = await askCredentials(profile.url,
    t("StorageWeb: token for {0} ({1})", store.title(profile), profile.username), profile.username);
  if (!credentials) return;
  const { token } = credentials;
  if (!(await checkAccess(new DavClient(profile.url, profile.username, token)))) return;
  await store.setToken(profile, token);
  serverChanged(profile.id);
  for (const folder of foldersOf(profile)) await startFolder(folder);
  vscode.window.showInformationMessage(t("StorageWeb: token saved for {0}.", store.title(profile)));
}

async function editServerCommand(/** @type {any} */ node) {
  const profile = await profileArg(node);
  if (!profile) return;
  const choice = await vscode.window.showQuickPick([
    { label: `$(edit) ${t("Rename…")}`, action: "label" },
    { label: `$(globe) ${t("Change address…")}`, description: profile.url, action: "url" },
    { label: `$(key) ${t("Change token…")}`, action: "token" },
  ], { placeHolder: store.title(profile) });
  if (!choice) return;
  if (choice.action === "token") return setTokenCommand({ profile });
  if (choice.action === "label") {
    const label = await vscode.window.showInputBox({ prompt: t("Name shown in the panel (empty: the address)"),
      value: profile.label || hostOf(profile.url), ignoreFocusOut: true });
    if (label === undefined) return;
    await store.update(profile.id, { label: label.trim() === hostOf(profile.url) ? "" : label });
    serverChanged(profile.id);
    return;
  }
  const url = await vscode.window.showInputBox({ prompt: t("Address of StorageWeb"), value: profile.url,
    ignoreFocusOut: true, validateInput: (v) => (normalizeUrl(v) ? null : t("For example https://files.company.com")) });
  const cleanUrl = url && normalizeUrl(url);
  if (!cleanUrl || cleanUrl === profile.url) return;
  const token = await store.token(profile);
  if (token && !(await checkAccess(new DavClient(cleanUrl, profile.username, token)))) return;
  const linked = foldersOf(profile);
  try {
    await store.update(profile.id, { url: cleanUrl });
  } catch (err) {
    showError(err);
    return;
  }
  for (const folder of linked) {  // las carpetas sincronizadas siguen con él
    await vscode.workspace.getConfiguration(SECTION, folder.uri).update("server", cleanUrl,
      vscode.ConfigurationTarget.WorkspaceFolder);
  }
  serverChanged(profile.id);
}

async function removeServerCommand(/** @type {any} */ node) {
  const profile = await profileArg(node);
  if (!profile) return;
  const linked = foldersOf(profile);
  const remove = t("Remove");
  const answer = await vscode.window.showWarningMessage(
    t("Remove «{0}» from the list? Its token is deleted from this computer; nothing is deleted on the server.",
      store.title(profile)),
    { modal: true, detail: linked.length
      ? t("These folders stop synchronizing: {0}", linked.map((f) => f.name).join(", ")) : undefined }, remove);
  if (answer !== remove) return;
  await store.remove(profile.id);
  serverChanged(profile.id);
  for (const folder of linked) await startFolder(folder);
}

// --------------------------------------------------------------------------- archivos del servidor

/** @param {any} node */
function nodeUri(node) {
  return remoteUri(node.profile.id, node.kind === "server" ? "" : node.path);
}

/** ¿Existe? (archivo o carpeta, aquí o en el servidor) @param {vscode.Uri} uri */
async function exists(uri) {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

/**
 * Copia (subir o bajar) varios archivos o carpetas; pregunta antes de reemplazar lo que ya exista.
 * @param {{from: vscode.Uri, to: vscode.Uri}[]} pairs @param {string} title
 */
async function copyAll(pairs, title) {
  let replaceAll = false;
  let done = 0;
  await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title, cancellable: true },
    async (progress, cancel) => {
      for (const { from, to } of pairs) {
        if (cancel.isCancellationRequested) break;
        const name = path.posix.basename(to.path);
        progress.report({ message: name, increment: 100 / pairs.length });
        let overwrite = false;
        if (await exists(to)) {
          if (!replaceAll) {
            const replace = t("Replace"), all = t("Replace all");
            const answer = await vscode.window.showWarningMessage(t("«{0}» already exists. Replace it?", name),
              { modal: true }, replace, ...(pairs.length > 1 ? [all] : []), t("Skip"));
            if (answer === all) replaceAll = true;
            else if (answer !== replace) continue;
          }
          overwrite = true;
        }
        try {
          await vscode.workspace.fs.copy(from, to, { overwrite });
          done++;
        } catch (err) {
          showError(err);
        }
      }
    });
  return done;
}

async function newFolderCommand(/** @type {any} */ node) {
  if (!node || !node.profile) return;
  const name = await vscode.window.showInputBox({ prompt: t("Name of the new folder"), ignoreFocusOut: true,
    validateInput: validName });
  if (!name) return;
  try {
    await vscode.workspace.fs.createDirectory(remoteUri(node.profile.id, `${node.path}/${name.trim()}`));
  } catch (err) {
    showError(err);
  }
}

/** @param {string} value */
function validName(value) {
  const v = value.trim();
  return v && v !== "." && v !== ".." && /^[^\\/:*?"<>|\x00-\x1f]+$/.test(v) ? null : t("Invalid name");
}

/** @param {any} node @param {boolean} folders */
async function upload(node, folders) {
  if (!node || !node.profile) return;
  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: !folders, canSelectFolders: folders, canSelectMany: true, openLabel: t("Upload"),
    title: t("Upload to «{0}»", node.path),
  });
  if (!picked || !picked.length) return;
  const pairs = picked.map((from) => ({ from, to: remoteUri(node.profile.id, `${node.path}/${path.basename(from.fsPath)}`) }));
  const done = await copyAll(pairs, t("Uploading to «{0}»…", node.path));
  if (done) log(t("Uploaded {0} item(s) to {1}", done, `${store.title(node.profile)}/${node.path}`));
}

async function downloadCommand(/** @type {any} */ node) {
  if (!node || !node.profile) return;
  const base = (vscode.workspace.workspaceFolders || []).find((f) => f.uri.scheme === "file");
  const defaultDir = base ? base.uri : vscode.Uri.file(os.homedir());
  const from = nodeUri(node);
  if (!node.isDir) {
    const to = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.joinPath(defaultDir, node.name),
      title: t("Download «{0}»", node.name) });
    if (!to) return;
    try {
      await vscode.workspace.fs.copy(from, to, { overwrite: true });  // el diálogo ya preguntó si reemplazar
    } catch (err) {
      showError(err);
    }
    return;
  }
  const dest = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false, defaultUri: defaultDir,
    openLabel: t("Download here"), title: t("Download «{0}» into…", node.name) });
  if (!dest || !dest.length) return;
  const to = vscode.Uri.joinPath(dest[0], node.name);
  if (await copyAll([{ from, to }], t("Downloading «{0}»…", node.name))) {
    const reveal = t("Show");
    vscode.window.showInformationMessage(t("StorageWeb: «{0}» downloaded.", node.name), reveal)
      .then((c) => c && vscode.commands.executeCommand("revealFileInOS", to));
  }
}

async function renameCommand(/** @type {any} */ node) {
  if (!node || !node.profile || !node.path.includes("/")) return;
  const dot = node.isDir ? -1 : node.name.lastIndexOf(".");
  const name = await vscode.window.showInputBox({ prompt: t("New name"), value: node.name, ignoreFocusOut: true,
    valueSelection: [0, dot > 0 ? dot : node.name.length], validateInput: validName });
  if (!name || name.trim() === node.name) return;
  const to = remoteUri(node.profile.id, `${parentOf(node.path)}/${name.trim()}`);
  try {
    await vscode.workspace.fs.rename(nodeUri(node), to, { overwrite: false });
  } catch (err) {
    showError(err instanceof vscode.FileSystemError && err.code === "FileExists"
      ? new Error(t("«{0}» already exists.", name.trim())) : err);
  }
}

async function deleteCommand(/** @type {any} */ node) {
  if (!node || !node.profile || !node.path.includes("/")) return;
  const remove = t("Delete");
  const answer = await vscode.window.showWarningMessage(
    node.isDir ? t("Delete the folder «{0}» and everything inside from the server?", node.name)
      : t("Delete «{0}» from the server?", node.name),
    { modal: true, detail: t("This cannot be undone.") }, remove);
  if (answer !== remove) return;
  try {
    await vscode.workspace.fs.delete(nodeUri(node), { recursive: true, useTrash: false });
  } catch (err) {
    showError(err);
  }
}

async function addToWorkspaceCommand(/** @type {any} */ node) {
  if (!node || !node.profile) return;
  const uri = nodeUri(node);
  if ((vscode.workspace.workspaceFolders || []).some((f) => f.uri.toString() === uri.toString())) return;
  const name = `${node.label || node.name} — ${store.title(node.profile)}`;
  const at = (vscode.workspace.workspaceFolders || []).length;
  if (!vscode.workspace.updateWorkspaceFolders(at, 0, { uri, name })) showError(new Error(t("Cannot add the folder.")));
}

// --------------------------------------------------------------------------- exclusiones

/**
 * Lo que no se sincroniza en una carpeta: lo de siempre (.git, node_modules, .venv…), `storageweb.exclude`,
 * el `.storagewebignore` de la carpeta y, si `storageweb.useGitignore`, su `.gitignore`.
 * @param {vscode.WorkspaceFolder} folder
 */
function exclusions(folder) {
  const cfg = vscode.workspace.getConfiguration(SECTION, folder.uri);
  const patterns = [...DEFAULT_EXCLUDES, ".vscode/settings.json", ...(cfg.get("exclude") || [])];
  const files = [IGNORE_FILE, ...(cfg.get("useGitignore") !== false ? [".gitignore"] : [])];
  for (const name of files) {
    let text;
    try {
      text = fs.readFileSync(path.join(folder.uri.fsPath, name), "utf8");
    } catch {
      continue;  // no existe
    }
    const parsed = ignorePatterns(text);
    patterns.push(...parsed.patterns);
    if (parsed.unsupported.length) {
      log(t("{0}: in {1}, lines with «!» are not supported and are ignored: {2}", folder.name, name,
        parsed.unsupported.join(", ")));
    }
  }
  return excluder(patterns);
}

/** El `.storagewebignore` de la carpeta, creándolo con una explicación si no existe. @param {vscode.WorkspaceFolder} folder */
async function ignoreFile(folder) {
  const uri = vscode.Uri.joinPath(folder.uri, IGNORE_FILE);
  try {
    await vscode.workspace.fs.stat(uri);
  } catch {
    const header = [
      `# ${t("StorageWeb: what is not synchronized in this folder (like .gitignore). This file is synchronized too.")}`,
      `# ${t("folder/ = that folder anywhere · /path = from here · *.log = by extension · # = comment")}`,
      `# ${t("Always excluded: .git, node_modules, .venv, venv, __pycache__ and temporary files.")}`,
      "",
    ].join("\n");
    await vscode.workspace.fs.writeFile(uri, Buffer.from(header + "\n", "utf8"));
  }
  return uri;
}

/** Añade líneas al `.storagewebignore` (las que no estén ya). @param {vscode.WorkspaceFolder} folder @param {string[]} lines */
async function addToIgnoreFile(folder, lines) {
  const uri = await ignoreFile(folder);
  const current = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString("utf8");
  const existing = new Set(current.split(/\r?\n/).map((l) => l.trim()));
  const added = lines.filter((l) => !existing.has(l));
  if (!added.length) return [];
  const text = current + (current.endsWith("\n") || !current ? "" : "\n") + added.join("\n") + "\n";
  await vscode.workspace.fs.writeFile(uri, Buffer.from(text, "utf8"));
  return added;
}

/** Explorador → «StorageWeb: No sincronizar»: añade lo elegido al `.storagewebignore`. */
async function excludeCommand(/** @type {vscode.Uri | undefined} */ uri, /** @type {vscode.Uri[] | undefined} */ uris) {
  const editor = vscode.window.activeTextEditor;
  const targets = (uris && uris.length ? uris : [uri || (editor && editor.document.uri)]).filter(Boolean);
  /** @type {Map<vscode.WorkspaceFolder, string[]>} */
  const byFolder = new Map();
  for (const target of /** @type {vscode.Uri[]} */ (targets)) {
    const folder = target.scheme === "file" ? vscode.workspace.getWorkspaceFolder(target) : undefined;
    if (!folder) continue;
    const rel = path.relative(folder.uri.fsPath, target.fsPath).split(path.sep).join("/");
    if (!rel || rel.startsWith("..") || rel === IGNORE_FILE) continue;
    let isDir = false;
    try {
      isDir = ((await vscode.workspace.fs.stat(target)).type & vscode.FileType.Directory) !== 0;
    } catch { /* ya no existe: como archivo */ }
    byFolder.set(folder, [...(byFolder.get(folder) || []), `/${rel}${isDir ? "/" : ""}`]);
  }
  if (!byFolder.size) {
    vscode.window.showInformationMessage(t("Choose files or folders of a folder of this window."));
    return;
  }
  for (const [folder, lines] of byFolder) {
    await addToIgnoreFile(folder, lines);
    vscode.window.showInformationMessage(
      t("StorageWeb: «{0}» will not be synchronized (added to {1}). What is already on the server stays there.",
        lines.map((l) => l.replace(/^\//, "")).join(", "), IGNORE_FILE));
    if (running.has(folder.uri.toString())) await startFolder(folder);
  }
}

/** Abrir el `.storagewebignore` de una carpeta (creándolo si hace falta). */
async function editExcludesCommand(/** @type {any} */ given) {
  const folder = await pickFolder(given);
  if (!folder) return;
  await vscode.window.showTextDocument(await ignoreFile(folder));
}

// --------------------------------------------------------------------------- una carpeta sincronizada

class FolderSync {
  /** @param {vscode.WorkspaceFolder} folder @param {{server: string, username: string, remoteFolder: string}} bind @param {string} token */
  constructor(folder, bind, token) {
    this.folder = folder;
    this.bind = bind;
    const cfg = vscode.workspace.getConfiguration(SECTION, folder.uri);
    const skip = exclusions(folder);
    this.skip = skip;
    this.client = new DavClient(bind.server, bind.username, token);
    const id = crypto.createHash("sha1").update(`${folder.uri}|${bind.server}|${bind.remoteFolder}`).digest("hex");
    this.stateUri = vscode.Uri.joinPath(ctx.globalStorageUri, `state-${id}.json`);
    this.engine = new SyncEngine({
      local: new LocalFs(folder.uri.fsPath, skip,
        (abs) => Promise.resolve(vscode.workspace.fs.delete(vscode.Uri.file(abs), { useTrash: true }))),
      remote: this.client,
      remoteRoot: bind.remoteFolder,
      store: { load: () => this.loadState(), save: (s) => this.saveState(s) },
      skip,
      log: (m) => log(`${folder.name}: ${m}`),
      conflictLabel: t("conflict"),
    });
    this.pollSeconds = Math.max(15, Number(cfg.get("pollSeconds")) || 60);
    this.autoSync = cfg.get("autoSync") !== false;
    this.maxDeletes = Number(cfg.get("confirmDeletesOver"));
    /** @type {Promise<unknown>} las operaciones van de una en una */
    this.queue = Promise.resolve();
    /** @type {Set<string>} */
    this.pending = new Set();
    this.timer = undefined;
    this.debounce = undefined;
    /** @type {Date | undefined} */
    this.lastSync = undefined;
    /** @type {string | undefined} */
    this.error = undefined;
    this.busy = false;
    this.stopped = false;
    this.loopChecked = false;  // la primera pasada comprueba que no se sincroniza consigo misma
    this.queuedSync = false;
    this.lastDuration = 0;
    this.lastEnd = 0;
    this.reload = undefined;
    this.disposables = [];
  }

  async loadState() {
    try {
      const raw = JSON.parse(Buffer.from(await vscode.workspace.fs.readFile(this.stateUri)).toString("utf8"));
      return new Map(Object.entries(raw.files || {}));
    } catch {
      return new Map();
    }
  }

  async saveState(state) {
    await vscode.workspace.fs.createDirectory(ctx.globalStorageUri);
    const body = JSON.stringify({ version: 1, files: Object.fromEntries(state) });
    await vscode.workspace.fs.writeFile(this.stateUri, Buffer.from(body, "utf8"));
  }

  start() {
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(this.folder, "**/*"));
    const queue = (/** @type {vscode.Uri} */ uri) => this.changed(uri);
    this.disposables.push(watcher, watcher.onDidCreate(queue), watcher.onDidChange(queue), watcher.onDidDelete(queue));
    this.timer = setInterval(() => this.tick(), Math.min(this.pollSeconds, 30) * 1000);
    this.sync();
  }

  /**
   * Del temporizador: una sincronización completa si toca. Nunca se acumulan (si hay una en marcha o en
   * cola, no se pide otra) y, si la última tardó mucho, se espera más (el triple de lo que tardó).
   */
  tick() {
    if (this.stopped || this.busy || this.queuedSync) return;
    if (Date.now() - this.lastEnd < Math.max(this.pollSeconds * 1000, this.lastDuration * 3)) return;
    this.sync();
  }

  /** Deja de vigilar y de sincronizar sola (lo que esté en marcha sigue; ver stop). */
  pause() {
    clearInterval(this.timer);
    clearTimeout(this.debounce);
    clearTimeout(this.reload);
    for (const d of this.disposables) d.dispose();
    this.disposables = [];
  }

  /** Para del todo, también la pasada en curso (en cuanto termine el archivo que está tratando). */
  stop() {
    this.pause();
    this.stopped = true;
    this.engine.cancel();
  }

  /** @param {vscode.Uri} uri */
  changed(uri) {
    const rel = path.relative(this.folder.uri.fsPath, uri.fsPath).split(path.sep).join("/");
    if (!rel || rel.startsWith("..")) return;
    if (rel === IGNORE_FILE || (rel === ".gitignore" && vscode.workspace.getConfiguration(SECTION, this.folder.uri)
      .get("useGitignore") !== false)) {
      clearTimeout(this.reload);  // cambiaron las exclusiones: se vuelve a empezar con las nuevas
      this.reload = setTimeout(() => startFolder(this.folder), 1500);
    }
    if (!this.autoSync || this.skip(rel)) return;
    this.pending.add(rel);
    clearTimeout(this.debounce);
    this.debounce = setTimeout(() => this.push(), 1500);
  }

  /** Una operación detrás de otra, con el estado «sincronizando» mientras dura. @param {() => Promise<void>} job */
  serial(job) {
    const run = async () => {
      if (this.stopped) return;
      this.busy = true;
      updateStatus();
      try {
        await job();
      } catch (err) {
        this.fail(err);
      }
      this.busy = false;
      updateStatus();
    };
    const next = this.queue.then(run, run);
    this.queue = next.catch(() => undefined);
    return next;
  }

  push() {
    const paths = [...this.pending];
    this.pending.clear();
    if (!paths.length) return Promise.resolve();
    return this.serial(async () => {
      const clean = await this.engine.push(paths);
      this.error = undefined;
      this.lastSync = new Date();
      if (!clean) await this.fullSync();  // cambió en el servidor entre medias
    });
  }

  /** Sincronización completa (también desde el comando y el temporizador). Si ya hay una en cola, esa. */
  sync() {
    if (this.queuedSync) return this.queue;
    this.queuedSync = true;
    return this.serial(async () => {
      this.queuedSync = false;
      const started = Date.now();
      try {
        await this.fullSync();
      } finally {
        this.lastDuration = Date.now() - started;
        this.lastEnd = Date.now();
      }
    });
  }

  async fullSync() {
    const summary = await this.engine.run({
      checkLoop: !this.loopChecked,
      maxDeletes: Number.isFinite(this.maxDeletes) ? this.maxDeletes : 10,
      confirmDeletes: async (count) => {
        const remove = t("Delete them");
        const answer = await vscode.window.showWarningMessage(
          t("StorageWeb: {0} files would be deleted in «{1}» because they disappeared on the other side. Delete them?",
            count, this.folder.name),
          { modal: true, detail: t("If you do not delete them, they are restored from the side that still has them.") },
          remove, t("Do not delete (restore)"));
        return answer === remove;
      },
    });
    this.loopChecked = true;
    this.lastSync = new Date();
    this.error = summary.errors.length ? summary.errors[0].error : undefined;
    for (const { path: rel, copy } of summary.conflicts) {
      const compare = t("Compare");
      vscode.window.showWarningMessage(
        t("StorageWeb: «{0}» changed here and on the server. The server version keeps the name; yours is in «{1}».",
          rel, copy), compare).then((choice) => {
        if (choice !== compare) return;
        const left = vscode.Uri.joinPath(this.folder.uri, ...copy.split("/"));
        const right = vscode.Uri.joinPath(this.folder.uri, ...rel.split("/"));
        vscode.commands.executeCommand("vscode.diff", left, right, t("{0}: yours ↔ server", path.basename(rel)));
      });
    }
    if (summary.hidden) {
      log(t("{0}: {1} files are hidden on the server (storage.hidden): they stay only on this computer.",
        this.folder.name, summary.hidden));
    }
    if (summary.uploaded || summary.downloaded || summary.deletedLocal || summary.deletedRemote) {
      log(t("{0}: ↑ {1} · ↓ {2} · deleted {3}", this.folder.name, summary.uploaded, summary.downloaded,
        summary.deletedLocal + summary.deletedRemote));
    }
  }

  fail(err) {
    const message = err instanceof Error ? err.message : String(err);
    this.error = message;
    log(`${this.folder.name}: ${message}`);
    if (err instanceof SyncLoopError) {
      this.pause();  // no se sincroniza sola; «Sincronizar ahora» lo vuelve a comprobar
      this.error = err.localDir ? t("it contains the server copy of «{0}» ({1})", this.bind.remoteFolder, err.localDir)
        : t("it is the server copy of «{0}»", this.bind.remoteFolder);
      const exclude = t("Exclude «{0}»", err.localDir), unlink = t("Unlink");
      const buttons = err.localDir ? [exclude, unlink] : [unlink];
      vscode.window.showErrorMessage(err.localDir
        ? t("StorageWeb: «{0}» was not synchronized: «{1}» inside it is where the server keeps «{2}». Each upload would appear again inside the folder, endlessly.",
          this.folder.name, err.localDir, this.bind.remoteFolder)
        : t("StorageWeb: «{0}» is the very folder where the server keeps «{1}»: it cannot be synchronized with itself.",
          this.folder.name, this.bind.remoteFolder), { modal: true }, ...buttons).then(async (choice) => {
        if (choice === exclude) {
          await addToIgnoreFile(this.folder, [`/${err.localDir}/`]);
          await startFolder(this.folder);
        } else if (choice === unlink) {
          await unlinkCommand(this.folder);
        }
      });
      return;
    }
    if (err instanceof DavError && err.status === 401) {
      this.stop();
      running.delete(this.folder.uri.toString());
      const profile = store.find(this.bind.server, this.bind.username);
      const fix = t("Change token…");
      vscode.window.showErrorMessage(
        t("StorageWeb: the server rejected the user or the token of «{0}» (revoked or expired?).", this.folder.name),
        fix).then((c) => c && (profile ? setTokenCommand({ profile })
        : vscode.commands.executeCommand("storageweb.link", this.folder)));
    }
  }
}

// --------------------------------------------------------------------------- estado (barra y panel)

/** @returns {import("./views").SyncInfo[]} */
function syncInfos() {
  const infos = [];
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const bind = binding(folder);
    if (!bind) continue;
    const s = running.get(folder.uri.toString());
    /** @type {import("./views").SyncInfo["state"]} */
    const state = isPaused(folder) ? "paused" : !s ? "notoken" : s.busy ? "busy" : s.error ? "error"
      : s.lastSync ? "ok" : "waiting";
    infos.push({ folder, ...bind, state, error: s && s.error, lastSync: s && s.lastSync });
  }
  return infos;
}

function updateStatus() {
  if (syncTree) syncTree.refresh();
  const all = [...running.values()];
  const paused = (vscode.workspace.workspaceFolders || []).filter((f) => binding(f) && isPaused(f));
  if (!all.length && paused.length) {
    status.text = "$(debug-pause) StorageWeb";
    status.tooltip = t("Synchronization paused: {0}", paused.map((f) => f.name).join(", "));
    status.show();
    return;
  }
  if (!all.length) {
    status.hide();
    return;
  }
  const busy = all.some((s) => s.busy);
  const failed = all.find((s) => s.error);
  status.text = busy ? "$(sync~spin) StorageWeb" : failed ? "$(warning) StorageWeb" : "$(cloud) StorageWeb";
  const lines = all.map((s) => {
    const where = `${s.bind.server}/f/${s.bind.remoteFolder}`;
    const when = s.lastSync ? t("synchronized at {0}", s.lastSync.toLocaleTimeString()) : t("not synchronized yet");
    return `${s.folder.name} ⇄ ${where} — ${s.error ? t("error: {0}", s.error) : when}`;
  });
  for (const f of paused) lines.push(`${f.name} — ${t("paused")}`);
  status.tooltip = lines.join("\n");
  status.show();
}

// --------------------------------------------------------------------------- pausa

/** Carpetas en pausa (en este espacio de trabajo; se mantiene al recargar). @returns {string[]} */
function pausedList() {
  const value = ctx.workspaceState.get(PAUSED);
  return Array.isArray(value) ? value : [];
}

/** @param {vscode.WorkspaceFolder} folder */
function isPaused(folder) {
  return pausedList().includes(folder.uri.toString());
}

/** @param {vscode.WorkspaceFolder[]} folders @param {boolean} paused */
async function setPaused(folders, paused) {
  const keys = new Set(pausedList());
  for (const folder of folders) {
    if (paused) keys.add(folder.uri.toString());
    else keys.delete(folder.uri.toString());
  }
  await ctx.workspaceState.update(PAUSED, [...keys]);
  for (const folder of folders) {
    await startFolder(folder);  // en pausa: se para (también la pasada en curso); si no, arranca
    log(paused ? t("{0}: paused", folder.name) : t("{0}: resumed", folder.name));
  }
  updatePausedContext();
}

/** Para los botones de «Pausar todo» / «Reanudar todo». */
function updatePausedContext() {
  const linked = (vscode.workspace.workspaceFolders || []).filter((f) => binding(f));
  vscode.commands.executeCommand("setContext", "storageweb.allPaused",
    linked.length > 0 && linked.every((f) => isPaused(f)));
}

/** Las carpetas de un nodo del panel o, sin él, todas las sincronizadas de esta ventana. */
function targetsOf(/** @type {any} */ node) {
  if (node && node.info) return [node.info.folder];
  if (node && node.uri) return [node];
  return (vscode.workspace.workspaceFolders || []).filter((f) => binding(f));
}

async function pauseCommand(/** @type {any} */ node) {
  const folders = targetsOf(node).filter((f) => !isPaused(f));
  if (folders.length) await setPaused(folders, true);
}

async function resumeCommand(/** @type {any} */ node) {
  const folders = targetsOf(node).filter((f) => isPaused(f));
  if (folders.length) await setPaused(folders, false);
}

// --------------------------------------------------------------------------- arranque

async function startFolder(/** @type {vscode.WorkspaceFolder} */ folder) {
  const key = folder.uri.toString();
  const generation = (starts.get(key) || 0) + 1;
  starts.set(key, generation);
  const stopOld = () => {
    const old = running.get(key);
    if (old) old.stop();
    running.delete(key);
  };
  stopOld();
  const bind = binding(folder);
  if (!bind) {
    updateStatus();
    return;
  }
  let token = await ctx.secrets.get(secretKey(bind.server, bind.username));
  let profile = store.find(bind.server, bind.username);
  if (!token && profile) token = await store.token(profile);
  if (token && !profile && normalizeUrl(bind.server)) {  // vinculada antes del panel: aparece en Servidores
    profile = await store.add({ url: bind.server, username: bind.username }, token);
    serversTree.refresh();
  }
  if (starts.get(key) !== generation) return;  // llegó otra orden de arranque mientras tanto: manda esa
  stopOld();
  if (isPaused(folder)) {
    updateStatus();
    return;
  }
  if (!token) {
    log(t("{0}: linked to {1} but there is no token on this computer: run «StorageWeb: Link folder».",
      folder.name, bind.server));
    updateStatus();
    return;
  }
  const sync = new FolderSync(folder, bind, token);
  running.set(key, sync);
  sync.start();
  updateStatus();
}

/** @param {vscode.Uri} uri */
function pendingKey(uri) {
  const p = path.resolve(uri.fsPath);
  return process.platform === "win32" ? p.toLowerCase() : p;
}

/** Una vinculación pedida desde el panel para una carpeta que había que abrir antes. @param {vscode.WorkspaceFolder} folder */
async function applyPending(folder) {
  if (folder.uri.scheme !== "file") return false;
  const pending = ctx.globalState.get(PENDING) || {};
  const key = pendingKey(folder.uri);
  const link = pending[key];
  if (!link) return false;
  delete pending[key];
  for (const [k, v] of Object.entries(pending)) if (Date.now() - (v.at || 0) > 86400000) delete pending[k];
  await ctx.globalState.update(PENDING, pending);
  const profile = store.get(link.profile);
  if (!profile || binding(folder)) return false;
  await applyLink(folder, profile, link.remoteFolder);
  return true;
}

async function startAll() {
  for (const folder of vscode.workspace.workspaceFolders || []) {
    if (!(await applyPending(folder))) await startFolder(folder);
  }
  for (const key of [...running.keys()]) {  // carpetas que ya no están en el espacio de trabajo
    if (!(vscode.workspace.workspaceFolders || []).some((f) => f.uri.toString() === key)) {
      const s = running.get(key);
      if (s) s.stop();
      running.delete(key);
    }
  }
  updateStatus();
}

// --------------------------------------------------------------------------- vincular

/** @param {any} given @returns {Promise<vscode.WorkspaceFolder | undefined>} */
async function pickFolder(given, onlyLinked = false) {
  if (given && given.uri) return given;
  if (given && given.info && given.info.folder) return given.info.folder;  // nodo del panel Sincronización
  const folders = (vscode.workspace.workspaceFolders || []).filter((f) => f.uri.scheme === "file"
    && (!onlyLinked || binding(f)));
  if (!folders.length) {
    vscode.window.showInformationMessage(onlyLinked ? t("No folder is linked to StorageWeb.")
      : t("Open a folder first."));
    return undefined;
  }
  if (folders.length === 1) return folders[0];
  const choice = await vscode.window.showQuickPick(folders.map((f) => ({ label: f.name, description: f.uri.fsPath, folder: f })),
    { placeHolder: t("Folder") });
  return choice && choice.folder;
}

/** Navegar por las carpetas del servidor y elegir una. @param {DavClient} client */
async function pickRemoteFolder(client) {
  let current = "";
  for (;;) {
    const entries = (await client.list(current)).filter((e) => e.isDir).sort((a, b) => a.name.localeCompare(b.name));
    /** @type {(vscode.QuickPickItem & {action: string, value?: string})[]} */
    const items = [];
    if (current) {
      items.push({ label: `$(check) ${t("Use this folder")}`, description: current, action: "use" });
      items.push({ label: `$(new-folder) ${t("New folder here…")}`, action: "new" });
      items.push({ label: "$(arrow-up) ..", action: "up" });
    }
    for (const e of entries) items.push({ label: `$(folder) ${e.name}`, action: "open", value: e.path });
    const choice = await vscode.window.showQuickPick(items, {
      title: t("StorageWeb folder to synchronize with"),
      placeHolder: current ? current : t("Your personal folder («home») or a shared folder"),
      ignoreFocusOut: true,
    });
    if (!choice) return undefined;
    if (choice.action === "use") return current;
    if (choice.action === "up") current = current.split("/").slice(0, -1).join("/");
    else if (choice.action === "open") current = /** @type {string} */ (choice.value);
    else if (choice.action === "new") {
      const name = await vscode.window.showInputBox({ prompt: t("Name of the new folder"), ignoreFocusOut: true,
        validateInput: validName });
      if (name) {
        await client.mkdirs(`${current}/${name.trim()}`);
        return `${current}/${name.trim()}`;
      }
    }
  }
}

/** @param {vscode.WorkspaceFolder} folder @param {import("./servers").ServerProfile} profile @param {string} remoteFolder */
async function applyLink(folder, profile, remoteFolder) {
  const cfg = vscode.workspace.getConfiguration(SECTION, folder.uri);
  const target = vscode.ConfigurationTarget.WorkspaceFolder;
  await cfg.update("server", profile.url, target);
  await cfg.update("username", profile.username, target);
  await cfg.update("remoteFolder", remoteFolder, target);
  log(t("{0}: linked to {1}/f/{2}", folder.name, profile.url, remoteFolder));
  await startFolder(folder);
  vscode.window.showInformationMessage(t("StorageWeb: «{0}» is synchronized with «{1}».", folder.name, remoteFolder));
}

/** ¿Seguro? si la carpeta ya estaba vinculada a otra cosa. @param {vscode.WorkspaceFolder} folder */
async function confirmRelink(folder) {
  const bind = binding(folder);
  if (!bind) return true;
  const change = t("Change");
  return (await vscode.window.showWarningMessage(
    t("«{0}» is already synchronized with «{1}». Synchronize it with the new folder instead?", folder.name,
      `${hostOf(bind.server)} · ${bind.remoteFolder}`), { modal: true }, change)) === change;
}

async function linkCommand(/** @type {any} */ given) {
  const folder = await pickFolder(given);
  if (!folder) return;
  const profile = await pickProfile(true);
  if (!profile) return;
  let client = await clientFor(profile);
  if (!client) {
    const credentials = await askCredentials(profile.url, t("StorageWeb: link «{0}»", folder.name), profile.username);
    if (!credentials) return;
    await store.setToken(profile, credentials.token);
    serverChanged(profile.id);
    client = /** @type {DavClient} */ (await clientFor(profile));
  }
  let remoteFolder;
  try {
    await client.roots();
    remoteFolder = await pickRemoteFolder(client);
  } catch (err) {
    showError(err);
    return;
  }
  if (!remoteFolder || !(await confirmRelink(folder))) return;
  await applyLink(folder, profile, remoteFolder);
}

/** Desde el panel: sincronizar una carpeta del servidor con una de este equipo. */
async function syncWithLocalCommand(/** @type {any} */ node) {
  if (!node || !node.profile || !node.path) return;
  const picked = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false,
    openLabel: t("Synchronize with this folder"), title: t("Local folder to synchronize with «{0}»", node.path) });
  if (!picked || !picked.length) return;
  const local = picked[0];
  const folder = (vscode.workspace.workspaceFolders || []).find((f) => pendingKey(f.uri) === pendingKey(local));
  if (folder) {
    if (await confirmRelink(folder)) await applyLink(folder, node.profile, node.path);
    return;
  }
  // Hay que abrirla en VS Code primero: se apunta y se vincula al abrirse (puede ser en otra ventana)
  const pending = ctx.globalState.get(PENDING) || {};
  pending[pendingKey(local)] = { profile: node.profile.id, remoteFolder: node.path, at: Date.now() };
  await ctx.globalState.update(PENDING, pending);
  const here = t("Open here"), other = t("Open in a new window"), add = t("Add to this workspace");
  const options = (vscode.workspace.workspaceFolders || []).length ? [add, here, other] : [here, other];
  const choice = await vscode.window.showInformationMessage(
    t("To synchronize «{0}» it has to be open in VS Code.", path.basename(local.fsPath)),
    { modal: true, detail: t("The first synchronization joins both folders: nothing is deleted.") }, ...options);
  if (choice === add) {
    vscode.workspace.updateWorkspaceFolders((vscode.workspace.workspaceFolders || []).length, 0, { uri: local });
  } else if (choice === here || choice === other) {
    vscode.commands.executeCommand("vscode.openFolder", local, { forceNewWindow: choice === other });
  } else {
    delete pending[pendingKey(local)];
    await ctx.globalState.update(PENDING, pending);
  }
}

async function unlinkCommand(/** @type {any} */ given) {
  const folder = await pickFolder(given, true);
  if (!folder) return;
  const unlink = t("Unlink");
  const answer = await vscode.window.showWarningMessage(
    t("Stop synchronizing «{0}»? Nothing is deleted, neither here nor on the server.", folder.name),
    { modal: true }, unlink);
  if (answer !== unlink) return;
  const sync = running.get(folder.uri.toString());
  if (sync) {
    sync.stop();
    try {
      await vscode.workspace.fs.delete(sync.stateUri);
    } catch { /* sin estado */ }
  }
  running.delete(folder.uri.toString());
  const cfg = vscode.workspace.getConfiguration(SECTION, folder.uri);
  for (const key of ["server", "username", "remoteFolder"]) {
    await cfg.update(key, undefined, vscode.ConfigurationTarget.WorkspaceFolder);
  }
  updateStatus();
}

async function signOutCommand(/** @type {any} */ given) {
  const folder = await pickFolder(given, true);
  if (!folder) return;
  const bind = binding(folder);
  if (!bind) return;
  await ctx.secrets.delete(secretKey(bind.server, bind.username));
  const profile = store.find(bind.server, bind.username);
  if (profile) {
    await store.forgetToken(profile);
    serverChanged(profile.id);
  }
  for (const f of vscode.workspace.workspaceFolders || []) {
    const b = binding(f);
    if (b && b.server === bind.server && b.username === bind.username) await startFolder(f);
  }
  vscode.window.showInformationMessage(t("StorageWeb: the token was removed from this computer."));
}

async function syncNowCommand(/** @type {any} */ node) {
  if (node && node.info && node.info.state === "paused") {
    await setPaused([node.info.folder], false);
    return;
  }
  if (node && node.info) {
    const s = running.get(node.info.folder.uri.toString());
    if (s) await s.sync();
    else if (node.info.state === "notoken") await linkCommand(node.info.folder);
    return;
  }
  if (!running.size) {
    vscode.window.showInformationMessage(t("No folder is linked to StorageWeb."), t("Link folder"))
      .then((c) => c && vscode.commands.executeCommand("storageweb.link"));
    return;
  }
  await Promise.all([...running.values()].map((s) => s.sync()));
}

/** @param {string} url @param {string} folderPath */
function webUrl(url, folderPath) {
  const parts = folderPath.split("/").filter((p) => p && p !== ".");
  return vscode.Uri.parse(`${url}/f/${parts.map(encodeURIComponent).join("/")}`);
}

async function openInBrowserCommand(/** @type {any} */ node) {
  if (node && node.kind === "server") return vscode.env.openExternal(vscode.Uri.parse(node.profile.url));
  if (node && node.kind === "entry") {
    return vscode.env.openExternal(webUrl(node.profile.url, node.isDir ? node.path : parentOf(node.path)));
  }
  const editor = vscode.window.activeTextEditor;
  if (!node && editor && editor.document.uri.scheme === SCHEME) {
    const profile = store.get(editor.document.uri.authority);
    if (profile) return vscode.env.openExternal(webUrl(profile.url, parentOf(editor.document.uri.path)));
  }
  const folder = node && node.info ? node.info.folder
    : (editor && vscode.workspace.getWorkspaceFolder(editor.document.uri)) || await pickFolder(undefined, true);
  if (!folder) return;
  const bind = binding(folder);
  if (!bind) return;
  let rel = "";
  if (!node && editor && vscode.workspace.getWorkspaceFolder(editor.document.uri) === folder) {
    rel = path.dirname(path.relative(folder.uri.fsPath, editor.document.uri.fsPath)).split(path.sep).join("/");
  }
  return vscode.env.openExternal(webUrl(bind.server, `${bind.remoteFolder}/${rel}`));
}

async function menuCommand() {
  const items = [
    { label: `$(sync) ${t("Synchronize now")}`, command: "storageweb.syncNow" },
    { label: `$(link-external) ${t("Open in the browser")}`, command: "storageweb.openInBrowser" },
    { label: `$(output) ${t("Show log")}`, command: "storageweb.showLog" },
    running.size
      ? { label: `$(debug-pause) ${t("Pause synchronization")}`, command: "storageweb.pause" }
      : { label: `$(debug-start) ${t("Resume synchronization")}`, command: "storageweb.resume" },
    { label: `$(debug-disconnect) ${t("Unlink folder…")}`, command: "storageweb.unlink" },
  ];
  const choice = await vscode.window.showQuickPick(items, { placeHolder: "StorageWeb" });
  if (choice) vscode.commands.executeCommand(choice.command);
}

// --------------------------------------------------------------------------- activación

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  ctx = context;
  output = vscode.window.createOutputChannel("StorageWeb");
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  status.command = "storageweb.menu";
  store = new ServerStore(context.globalState, context.secrets);
  remote = new RemoteFs(async (id) => {
    const profile = store.get(id);
    if (!profile) throw new RemoteFsError("FileNotFound", "", `Unknown StorageWeb server: ${id}`);
    const client = await clientFor(profile);
    if (!client) throw new RemoteFsError("NoPermissions", "", "The server rejected the user or the token");
    return client;
  });
  const fsProvider = new StorageWebFs(remote);
  serversTree = new ServersTree(store, remote);
  syncTree = new SyncTree(syncInfos);
  const serversView = vscode.window.createTreeView("storageweb.servers", { treeDataProvider: serversTree, showCollapseAll: true });
  const syncView = vscode.window.createTreeView("storageweb.syncs", { treeDataProvider: syncTree });
  const command = (/** @type {string} */ id, /** @type {(...args: any[]) => any} */ fn) =>
    vscode.commands.registerCommand(id, async (...args) => {
      try {
        return await fn(...args);
      } catch (err) {
        showError(err);
      }
    });
  context.subscriptions.push(
    output, status, serversView, syncView,
    vscode.workspace.registerFileSystemProvider(SCHEME, fsProvider, { isCaseSensitive: true }),
    vscode.window.registerUriHandler({ handleUri }),
    fsProvider.onDidChangeFile((events) => serversTree.changed(events)),
    command("storageweb.link", linkCommand),
    command("storageweb.unlink", unlinkCommand),
    command("storageweb.signOut", signOutCommand),
    command("storageweb.syncNow", syncNowCommand),
    command("storageweb.openInBrowser", openInBrowserCommand),
    command("storageweb.showLog", () => output.show()),
    command("storageweb.menu", menuCommand),
    command("storageweb.addServer", addServerCommand),
    command("storageweb.editServer", editServerCommand),
    command("storageweb.setToken", setTokenCommand),
    command("storageweb.removeServer", removeServerCommand),
    command("storageweb.refresh", () => serversTree.refresh()),
    command("storageweb.refreshNode", (node) => {
      if (node && node.profile) remote.forget(node.profile.id);
      serversTree.refresh(node && node.kind !== "message" ? node : undefined);
    }),
    command("storageweb.openRemote", (node) => node && node.profile
      && vscode.commands.executeCommand("vscode.open", nodeUri(node))),
    command("storageweb.newFolder", newFolderCommand),
    command("storageweb.uploadFiles", (node) => upload(node, false)),
    command("storageweb.uploadFolder", (node) => upload(node, true)),
    command("storageweb.download", downloadCommand),
    command("storageweb.rename", renameCommand),
    command("storageweb.delete", deleteCommand),
    command("storageweb.addToWorkspace", addToWorkspaceCommand),
    command("storageweb.syncWithLocal", syncWithLocalCommand),
    command("storageweb.exclude", excludeCommand),
    command("storageweb.pause", pauseCommand),
    command("storageweb.resume", resumeCommand),
    command("storageweb.editExcludes", editExcludesCommand),
    vscode.workspace.onDidChangeWorkspaceFolders(() => startAll().then(updatePausedContext)),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration(SECTION)) return;
      for (const folder of vscode.workspace.workspaceFolders || []) {
        if (e.affectsConfiguration(SECTION, folder.uri)) startFolder(folder);
      }
    }),
    { dispose: () => { for (const s of running.values()) s.stop(); running.clear(); } },
  );
  startAll().then(updatePausedContext);
}

function deactivate() {
  for (const s of running.values()) s.stop();
  running.clear();
}

module.exports = { activate, deactivate };

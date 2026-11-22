// La extensión cargada con un `vscode` simulado (test/vscode-mock.js): comandos, paneles y el sistema de
// archivos `storageweb://` (este último contra un StorageWeb de verdad, como server.test.js).
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const { createContext, createVscode, withVscode } = require("./vscode-mock");

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
const URL = process.env.STORAGEWEB_TEST_URL;
const skip = !URL && "sin servidor (STORAGEWEB_TEST_URL)";

function load(context = createContext()) {
  const { vscode, registered } = createVscode();
  const extension = withVscode(vscode, () => require("../src/extension"));
  extension.activate(context);
  return { vscode, registered, extension, context };
}

test("cada comando del package.json está registrado (y no hay otros), igual que los de los menús", () => {
  const { registered, extension } = load();
  const declared = manifest.contributes.commands.map((c) => c.command).sort();
  assert.deepEqual([...registered.commands.keys()].sort(), declared);
  const used = new Set();
  for (const items of Object.values(manifest.contributes.menus)) for (const item of items) used.add(item.command);
  for (const w of manifest.contributes.viewsWelcome) {
    for (const m of fs.readFileSync(path.join(__dirname, "..", "package.nls.json"), "utf8").matchAll(/command:([\w.]+)/g)) used.add(m[1]);
    assert.ok(manifest.contributes.views.storageweb.some((v) => v.id === w.view), w.view);
  }
  assert.deepEqual([...used].filter((c) => !declared.includes(c)), [], "menús con comandos que no existen");
  assert.deepEqual([...registered.trees.keys()].sort(), ["storageweb.servers", "storageweb.syncs"]);
  assert.ok(registered.fileSystems.has("storageweb"));
  assert.ok(fs.existsSync(path.join(__dirname, "..", manifest.contributes.viewsContainers.activitybar[0].icon)));
  extension.deactivate();
});

test("panel Servidores sin servidores: vacío (VS Code muestra el botón «Añadir servidor»)", async () => {
  const { registered, extension } = load();
  assert.deepEqual(await registered.trees.get("storageweb.servers").getChildren(), []);
  assert.deepEqual(await registered.trees.get("storageweb.syncs").getChildren(), []);
  extension.deactivate();
});

test("panel Servidores y archivos storageweb:// contra un StorageWeb real", { skip }, async () => {
  const context = createContext();
  const user = process.env.STORAGEWEB_TEST_USER;
  await context.globalState.update("storageweb.servers", [
    { id: "a1b2c3", url: URL, username: user, label: "" },
    { id: "bad000", url: URL.replace("127.0.0.1", "localhost"), username: user, label: "Mal" },
  ]);
  await context.secrets.store(`storageweb.token:${URL}|${user.toLowerCase()}`, process.env.STORAGEWEB_TEST_TOKEN);
  await context.secrets.store(`storageweb.token:${URL.replace("127.0.0.1", "localhost")}|${user.toLowerCase()}`, "sw_mal");
  const { vscode, registered, extension } = load(context);
  const tree = registered.trees.get("storageweb.servers");

  // Servidores → carpetas de arriba → carpetas y archivos
  const servers = await tree.getChildren();
  assert.deepEqual(servers.map((s) => s.profile.id).sort(), ["a1b2c3", "bad000"]);
  const good = servers.find((s) => s.profile.id === "a1b2c3");
  assert.equal(tree.getTreeItem(good).contextValue, "server");
  const roots = await tree.getChildren(good);
  const home = roots.find((n) => n.path === "home");
  assert.ok(home, "la carpeta personal");
  assert.equal(tree.getTreeItem(home).contextValue, "root");
  assert.equal(tree.getTreeItem(home).resourceUri.toString(), "storageweb://a1b2c3/home");

  // Token rechazado: un aviso que lleva a cambiarlo
  const [rejected] = await tree.getChildren(servers.find((s) => s.profile.id === "bad000"));
  assert.equal(rejected.kind, "message");
  assert.equal(rejected.command.command, "storageweb.setToken");

  // El sistema de archivos
  const provider = registered.fileSystems.get("storageweb");
  const uri = (p) => vscode.Uri.from({ scheme: "storageweb", authority: "a1b2c3", path: p });
  const code = (c) => (err) => { assert.equal(err.code, c, err.message); return true; };
  const dir = `/home/panel-${Date.now()}`;
  const events = [];
  provider.onDidChangeFile((e) => events.push(...e));
  let refreshed = 0;
  tree.onDidChangeTreeData(() => refreshed++);
  await tree.getChildren(home);  // «home» desplegada: se refresca al crear algo dentro

  await provider.createDirectory(uri(dir));
  assert.ok(events.some((e) => e.type === vscode.FileChangeType.Created && e.uri.path === dir));
  assert.ok(refreshed >= 1, "el panel se refresca");
  await assert.rejects(provider.createDirectory(uri(dir)), code("FileExists"));
  await assert.rejects(provider.createDirectory(uri(`${dir}/no/existe`)), code("FileNotFound"));

  await provider.writeFile(uri(`${dir}/a ñ.txt`), Buffer.from("uno"), { create: true, overwrite: false });
  assert.equal(Buffer.from(await provider.readFile(uri(`${dir}/a ñ.txt`))).toString(), "uno");
  const stat = await provider.stat(uri(`${dir}/a ñ.txt`));
  assert.equal(stat.type, vscode.FileType.File);
  assert.equal(stat.size, 3);
  assert.ok(stat.mtime > 0);
  await assert.rejects(provider.writeFile(uri(`${dir}/a ñ.txt`), Buffer.from("x"), { create: true, overwrite: false }),
    code("FileExists"));
  await assert.rejects(provider.writeFile(uri(`${dir}/nuevo.txt`), Buffer.from("x"), { create: false, overwrite: true }),
    code("FileNotFound"));
  await provider.writeFile(uri(`${dir}/a ñ.txt`), Buffer.from("dos"), { create: false, overwrite: true });
  assert.equal(Buffer.from(await provider.readFile(uri(`${dir}/a ñ.txt`))).toString(), "dos");
  assert.deepEqual(await provider.readDirectory(uri(dir)), [["a ñ.txt", vscode.FileType.File]]);

  // Lo abierto se vigila: lo que cambie otro en el servidor llega como evento (el editor lo recarga)
  const watchFile = provider.watch(uri(`${dir}/a ñ.txt`), { recursive: false, excludes: [] });
  const watchDir = provider.watch(uri(dir), { recursive: false, excludes: [] });
  await provider.poll();                                     // la primera vez solo toma nota
  events.length = 0;
  await provider.poll();
  assert.deepEqual(events, [], "sin cambios, sin avisos");
  await new Promise((r) => setTimeout(r, 1100));             // otra fecha de modificación
  await provider.remote.writeFile("a1b2c3", `${dir}/a ñ.txt`, Buffer.from("de otro"), { create: false, overwrite: true });
  await provider.remote.writeFile("a1b2c3", `${dir}/otro.txt`, Buffer.from("x"), { create: true, overwrite: false });
  await provider.poll();
  const changed = events.map((e) => `${e.type}:${e.uri.path}`).sort();
  assert.deepEqual(changed, [`${vscode.FileChangeType.Changed}:${dir}`, `${vscode.FileChangeType.Changed}:${dir}/a ñ.txt`]);
  events.length = 0;
  await provider.writeFile(uri(`${dir}/a ñ.txt`), Buffer.from("dos"), { create: false, overwrite: true });
  await provider.poll();                                     // lo guardado desde aquí ya se avisó: no se repite
  assert.deepEqual(events.filter((e) => e.type === vscode.FileChangeType.Changed && e.uri.path === `${dir}/a ñ.txt`),
    [{ type: vscode.FileChangeType.Changed, uri: uri(`${dir}/a ñ.txt`) }]);
  await provider.remote.delete("a1b2c3", `${dir}/otro.txt`);
  events.length = 0;
  await provider.poll();
  assert.deepEqual(events.map((e) => e.uri.path), [dir]);
  watchFile.dispose();
  watchDir.dispose();
  assert.equal(provider.watched.size, 0);
  await assert.rejects(provider.readDirectory(uri(`${dir}/a ñ.txt`)), code("FileNotADirectory"));
  await assert.rejects(provider.readFile(uri(dir)), code("FileIsADirectory"));
  await assert.rejects(provider.stat(uri(`${dir}/no.txt`)), code("FileNotFound"));
  await assert.rejects(provider.stat(uri(`${dir}/../../etc`)), code("NoPermissions"));

  // Renombrar y copiar (en el servidor); sin overwrite, no se pisa lo que ya existe
  await provider.rename(uri(`${dir}/a ñ.txt`), uri(`${dir}/b.txt`), { overwrite: false });
  await provider.copy(uri(`${dir}/b.txt`), uri(`${dir}/c.txt`), { overwrite: false });
  await assert.rejects(provider.rename(uri(`${dir}/b.txt`), uri(`${dir}/c.txt`), { overwrite: false }), code("FileExists"));
  await provider.writeFile(uri(`${dir}/c.txt`), Buffer.from("tres"), { create: false, overwrite: true });
  await provider.rename(uri(`${dir}/c.txt`), uri(`${dir}/b.txt`), { overwrite: true });
  assert.equal(Buffer.from(await provider.readFile(uri(`${dir}/b.txt`))).toString(), "tres");
  assert.deepEqual((await provider.readDirectory(uri(dir))).map(([n]) => n), ["b.txt"]);

  // El panel lo muestra dentro de su carpeta
  const folder = (await tree.getChildren(home)).find((n) => n.path === dir.slice(1));
  assert.equal(tree.getTreeItem(folder).contextValue, "folder");
  const [file] = await tree.getChildren(folder);
  const item = tree.getTreeItem(file);
  assert.equal(item.contextValue, "file");
  assert.equal(item.command.command, "vscode.open");

  // Borrar la carpeta con lo de dentro
  await provider.delete(uri(dir), { recursive: true });
  await assert.rejects(provider.stat(uri(dir)), code("FileNotFound"));
  await assert.rejects(provider.delete(uri(dir), { recursive: true }), code("FileNotFound"));
  extension.deactivate();
});

test("Añadir servidor eligiendo «Iniciar sesión en el navegador» (contra StorageWeb)", {
  skip: !(URL && process.env.STORAGEWEB_TEST_PASSWORD) && "sin servidor o sin contraseña de prueba",
}, async () => {
  const { browserSession } = require("./browser");
  const user = process.env.STORAGEWEB_TEST_USER;
  const browser = await browserSession(URL, user, process.env.STORAGEWEB_TEST_PASSWORD);
  const { vscode, registered, extension, context } = load();
  const asked = [];
  vscode.window.showInputBox = async (opts) => { asked.push(opts.prompt); return `${URL}/`; };  // solo la dirección
  vscode.window.showQuickPick = async (items) => items.find((i) => i.method === "browser");
  let opened;
  vscode.env.openExternal = async (uri) => {
    opened = uri.toString(true);
    // El usuario acepta en el navegador y este vuelve a VS Code (vscode://…/auth?code=…&state=…)
    browser.authorize(opened).then((back) => registered.uriHandler.handleUri(vscode.Uri.parse(back)));
    return true;
  };
  await registered.commands.get("storageweb.addServer")();
  assert.ok(opened.startsWith(`${URL}/connect/vscode?`), opened);
  assert.equal(asked.length, 1, "no pide usuario ni token");
  const tree = registered.trees.get("storageweb.servers");
  const [server] = await tree.getChildren();
  assert.equal(server.profile.username, user);
  assert.ok((await context.secrets.get(`storageweb.token:${URL}|${user.toLowerCase()}`)).startsWith("sw_"));
  assert.ok((await tree.getChildren(server)).some((n) => n.path === "home"), "con el token recibido entra");
  assert.deepEqual(registered.messages.filter((m) => m.kind === "error"), []);

  // Una vuelta que nadie espera (repetida o falsa) solo avisa
  registered.uriHandler.handleUri(vscode.Uri.parse("vscode://storageweb.storageweb-sync/auth?code=x&state=nadie-la-espera"));
  assert.ok(registered.messages.some((m) => m.kind === "warning"));
  extension.deactivate();
});

test("una carpeta en pausa: se ve así en el panel, no conecta y se reanuda desde el panel", async () => {
  const context = createContext();
  const { vscode } = createVscode();
  const folder = { name: "proyecto", index: 0, uri: vscode.Uri.file(path.join(require("node:os").tmpdir(), "sw-pausa")) };
  await context.workspaceState.update("storageweb.paused", [folder.uri.toString()]);
  await context.secrets.store("storageweb.token:http://127.0.0.1:9|ana", "sw_x");
  const { registered, extension } = (() => {
    const { vscode: v, registered: r } = createVscode();
    v.workspace.workspaceFolders = [folder];
    v.workspace.getConfiguration = () => ({
      get: (k) => ({ server: "http://127.0.0.1:9", username: "ana", remoteFolder: "home/p" })[k],
      update: async () => undefined,
    });
    let calls = 0;
    v.window.createTreeView = (id, o) => { r.trees.set(id, o.treeDataProvider); return { dispose() {} }; };
    const ext = withVscode(v, () => require("../src/extension"));
    const realFetch = global.fetch;
    global.fetch = async (...a) => { calls++; return realFetch(...a); };
    ext.activate(context);
    r.calls = () => calls;
    r.restore = () => { global.fetch = realFetch; };
    return { registered: r, extension: ext };
  })();
  await new Promise((resolve) => setTimeout(resolve, 50));
  const [node] = await registered.trees.get("storageweb.syncs").getChildren();
  assert.equal(node.info.state, "paused");
  const item = registered.trees.get("storageweb.syncs").getTreeItem(node);
  assert.equal(item.contextValue, "sync-paused");
  assert.equal(registered.calls(), 0, "en pausa no hace ninguna petición");
  // Pausar algo ya en pausa no hace nada; reanudar la quita de la lista
  await registered.commands.get("storageweb.pause")(node);
  await registered.commands.get("storageweb.resume")(node);
  assert.deepEqual(context.workspaceState.get("storageweb.paused"), []);
  await registered.commands.get("storageweb.pause")(node);  // y se vuelve a pausar (para la que arrancó)
  assert.deepEqual(context.workspaceState.get("storageweb.paused"), [folder.uri.toString()]);
  registered.restore();
  extension.deactivate();
});

// --------------------------------------------------------------------------- avisos cuando el servidor deniega algo

const MULTISTATUS = (where) => `<?xml version="1.0"?><D:multistatus xmlns:D="DAV:"><D:response><D:href>/dav/${where}/</D:href>
  <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response></D:multistatus>`;

/** Una respuesta de error de StorageWeb con su motivo (X-StorageWeb-Reason). */
const reason = (status, code, extra = {}) => new Response("", { status,
  headers: { ...(code ? { "X-StorageWeb-Reason": code } : {}), ...extra } });

/**
 * La extensión con carpetas vinculadas a un servidor falso: `answer(method, url)` da la respuesta de cada
 * petición. Devuelve lo registrado, las peticiones hechas y `until(fn)` para esperar a que pase algo.
 * @param {string[]} names @param {(method: string, url: string) => Response} answer
 */
function linked(names, answer) {
  const os = require("node:os");
  const context = createContext();
  const { vscode, registered } = createVscode();
  const server = "http://127.0.0.1:9";
  const folders = names.map((name, index) => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), `sw-${name}-`));
    fs.writeFileSync(path.join(dir, "mio.txt"), "local");
    return { name, index, uri: vscode.Uri.file(dir) };
  });
  vscode.workspace.workspaceFolders = folders;
  vscode.workspace.getConfiguration = (_section, uri) => ({
    get: (k) => ({ server, username: "ana", remoteFolder: `home/${uri ? path.basename(uri.path) : "x"}` })[k],
    update: async () => undefined,
  });
  vscode.workspace.fs = {
    readFile: async () => { throw new Error("ENOENT"); },
    writeFile: async () => undefined,
    createDirectory: async () => undefined,
    delete: async () => undefined,
    stat: async () => { throw new Error("ENOENT"); },
  };
  context.secrets.store(`storageweb.token:${server}|ana`, "sw_x");
  const calls = [];
  const realFetch = global.fetch;
  global.fetch = async (url, init) => {
    calls.push(`${init.method} ${url}`);
    return answer(init.method, String(url));
  };
  const extension = withVscode(vscode, () => require("../src/extension"));
  extension.activate(context);
  const until = async (/** @type {() => boolean} */ fn, ms = 3000) => {
    for (let waited = 0; !fn() && waited < ms; waited += 10) await new Promise((r) => setTimeout(r, 10));
    assert.ok(fn(), "no pasó a tiempo");
  };
  const syncs = () => registered.trees.get("storageweb.syncs").getChildren();
  const done = () => {
    extension.deactivate();
    global.fetch = realFetch;
    for (const f of folders) fs.rmSync(f.uri.fsPath, { recursive: true, force: true });
  };
  return { vscode, registered, calls, until, syncs, done, folders };
}

test("carpeta del servidor que ya no está: en pausa, un aviso y no se borra nada", async () => {
  const env = linked(["proyecto"], (method) => (method === "PROPFIND" ? reason(404) : reason(500)));
  try {
    await env.until(() => env.registered.messages.length > 0);
    const [msg] = env.registered.messages;
    assert.equal(msg.kind, "warning");
    assert.match(msg.text, /no longer have access to «home\/sw-proyecto-\w+» on the server, or it no longer exists/);
    assert.match(msg.text, /nothing has been deleted/);
    assert.deepEqual(msg.rest, ["Synchronize now", "Unlink"]);
    assert.ok(fs.existsSync(path.join(env.folders[0].uri.fsPath, "mio.txt")), "lo local sigue ahí");
    assert.ok(!env.calls.some((c) => !c.startsWith("PROPFIND")), "ni subidas ni pruebas: solo la consulta de la raíz");
    const [node] = env.syncs();
    assert.equal(node.info.state, "error");
    assert.match(node.info.error, /paused/);
  } finally {
    env.done();
  }
});

test("cuenta desactivada: se para y se avisa una vez aunque haya dos carpetas", async () => {
  const env = linked(["uno", "dos"], () => reason(401, "account_disabled"));
  try {
    await env.until(() => env.syncs().every((n) => n.info.state === "error"));
    const errors = env.registered.messages.filter((m) => m.kind === "error");
    assert.deepEqual(errors.map((m) => [m.text, m.rest]), [["Your StorageWeb account is disabled: ask an administrator.", []]]);
    assert.equal(env.syncs()[1].info.error, "Your StorageWeb account is disabled: ask an administrator.");
    const before = env.calls.length;
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(env.calls.length, before, "no insiste");
  } finally {
    env.done();
  }
});

test("token caducado: aviso con «Iniciar sesión otra vez» y «Cambiar el token…»", async () => {
  const env = linked(["p"], () => reason(401, "token_expired"));
  try {
    await env.until(() => env.registered.messages.length > 0);
    const [msg] = env.registered.messages;
    assert.equal(msg.kind, "error");
    assert.match(msg.text, /API token for «127\.0\.0\.1:9» has expired/);
    assert.deepEqual(msg.rest, ["Sign in again", "Change token…"]);
  } finally {
    env.done();
  }
});

test("mantenimiento: sin avisos, el estado lo dice y se reintenta en la próxima vuelta", async () => {
  const env = linked(["p"], () => reason(503, "maintenance", { "Retry-After": "30" }));
  try {
    await env.until(() => env.syncs()[0].info.state === "error");
    assert.match(env.syncs()[0].info.error, /maintenance/);
    assert.deepEqual(env.registered.messages, []);
  } finally {
    env.done();
  }
});

test("carpeta de solo lectura: un aviso (no uno por vuelta) y lo local se queda", async () => {
  const env = linked(["p"], (method, url) => {
    const rel = decodeURIComponent(url.replace(/^.*?\/dav\//, "").replace(/\/$/, ""));
    if (method === "PROPFIND") return new Response(MULTISTATUS(rel), { status: 207 });
    if (method === "PUT" || method === "MKCOL") return reason(403, "read_only");
    return reason(500);
  });
  try {
    await env.until(() => env.registered.messages.length > 0 && env.syncs()[0].info.state === "error");
    const [node] = env.syncs();
    await env.registered.commands.get("storageweb.syncNow")(node);  // otra vuelta: no se repite el aviso
    await env.registered.commands.get("storageweb.syncNow")(node);
    const warnings = env.registered.messages.filter((m) => m.kind === "warning");
    assert.equal(warnings.length, 1, JSON.stringify(env.registered.messages));
    assert.match(warnings[0].text, /cannot be uploaded to «home\/sw-p-\w+»: the folder is read-only for you\. They stay on this computer/);
    assert.equal(env.syncs()[0].info.error, "cannot upload changes: the folder is read-only for you");
    assert.ok(fs.existsSync(path.join(env.folders[0].uri.fsPath, "mio.txt")));
    assert.equal(env.calls.filter((c) => c.startsWith("PUT")).length, 3, "solo la prueba del bucle en cada vuelta");
  } finally {
    env.done();
  }
});

test("mensajes según el motivo del servidor (paneles y archivos storageweb://)", () => {
  const { vscode } = createVscode();
  const { messages, dav, remotefs, provider: prov } = withVscode(vscode, () => ({
    messages: require("../src/messages"), dav: require("../src/dav"), remotefs: require("../src/remotefs"),
    provider: require("../src/provider"),
  }));
  const { describe, needsToken } = messages;
  const { translate, RemoteFsError } = remotefs;
  const e = (status, code) => new dav.DavError(status, "x", false, "", code);
  assert.equal(describe(e(401, "token_expired")), "The API token has expired: sign in again or set a new token.");
  assert.equal(describe(e(401, "")), "The server rejected the user or the token.");
  assert.equal(describe(e(403, "ip_banned")), "The server has blocked the IP address of this computer: ask an administrator.");
  assert.equal(describe(e(403, "token_read_only")), "Not allowed: the API token only allows reading.");
  assert.equal(describe(e(503, "maintenance")), "The server is in maintenance (restoring a backup): try again in a moment.");
  assert.equal(describe(e(0, "interrupted")), "The transfer was interrupted before it finished: nothing was saved. Try again.");
  assert.equal(describe(translate(e(404, ""), "compartida/x")),
    "«compartida/x» does not exist on the server, or you no longer have access to it.");
  assert.ok(needsToken(e(401, "token_invalid")) && !needsToken(e(401, "account_disabled")) && !needsToken(e(403, "read_only")));

  // Al guardar un archivo storageweb:// en una carpeta de solo lectura, VS Code dice por qué
  const provider = new prov.StorageWebFs(/** @type {any} */ ({}));
  const uri = vscode.Uri.from({ scheme: "storageweb", authority: "s", path: "/compartida/a.txt" });
  const saved = provider.error(uri, translate(e(403, "read_only"), "compartida/a.txt"));
  assert.deepEqual([saved.code, saved.message], ["NoPermissions", "Not allowed: the folder is read-only for you."]);
  const big = provider.error(uri, translate(e(413, "too_large"), "compartida/a.txt"));
  assert.equal(big.message, "«a.txt»: The file is larger than the server allows.");
  const cut = provider.error(uri, translate(e(0, "interrupted"), "compartida/a.txt"));
  assert.equal(cut.code, "Unavailable");
  assert.match(provider.error(uri, new RemoteFsError("NoPermissions", "", "The server rejected the user or the token")).message,
    /rejected/);
  provider.dispose();
});

test("los archivos abiertos dejan de comprobarse si el servidor rechaza las credenciales (y se avisa una vez)", async () => {
  const { vscode } = createVscode();
  const { StorageWebFs, RemoteFsError } = withVscode(vscode, () => ({
    StorageWebFs: require("../src/provider").StorageWebFs, RemoteFsError: require("../src/remotefs").RemoteFsError,
  }));
  let asked = 0;
  const remote = { stat: async () => {
    asked++;
    throw new RemoteFsError("NoPermissions", "a", "The server rejected the user or the token",
      { status: 401, serverCode: "account_disabled" });
  } };
  const provider = new StorageWebFs(/** @type {any} */ (remote));
  const failed = [];
  provider.onPollError = (server, err) => failed.push([server, err.serverCode]);
  const uri = (p) => vscode.Uri.from({ scheme: "storageweb", authority: "s1", path: p });
  provider.watch(uri("/home/a.txt"));
  provider.watch(uri("/home/b.txt"));
  await provider.poll();
  await provider.poll();
  assert.equal(asked, 1, "una petición, no una por archivo ni por vuelta");
  assert.deepEqual(failed, [["s1", "account_disabled"]]);
  provider.unblock("s1");  // p. ej. tras poner un token nuevo
  await provider.poll();
  assert.equal(asked, 2);
  provider.dispose();
});

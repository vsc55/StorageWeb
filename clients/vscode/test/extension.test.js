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

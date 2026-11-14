// Contra un StorageWeb de verdad (lo arranca tests/integration/test_vscode_extension.py y pasa la
// dirección y el token en STORAGEWEB_TEST_URL / STORAGEWEB_TEST_USER / STORAGEWEB_TEST_TOKEN).
// Dos «equipos» (dos carpetas locales) sincronizan la misma carpeta del servidor.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const { DavClient } = require("../src/dav");
const { DEFAULT_EXCLUDES, excluder } = require("../src/glob");
const { LocalFs } = require("../src/localfs");
const { SyncEngine } = require("../src/sync");

const URL = process.env.STORAGEWEB_TEST_URL;
const skip = !URL && "sin servidor (STORAGEWEB_TEST_URL)";

async function machine(name) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), `sw-${name}-`));
  const stateFile = path.join(dir, "..", `${path.basename(dir)}.state.json`);
  const client = new DavClient(URL, process.env.STORAGEWEB_TEST_USER, process.env.STORAGEWEB_TEST_TOKEN);
  const skipFn = excluder([...DEFAULT_EXCLUDES]);
  const engine = new SyncEngine({
    local: new LocalFs(dir, skipFn), remote: client, remoteRoot: "home/proyecto", skip: skipFn, conflictLabel: "conflicto",
    store: {
      load: async () => { try { return new Map(Object.entries(JSON.parse(await fs.readFile(stateFile, "utf8")))); } catch { return new Map(); } },
      save: async (s) => fs.writeFile(stateFile, JSON.stringify(Object.fromEntries(s))),
    },
  });
  const write = (rel, text) => fs.mkdir(path.dirname(path.join(dir, rel)), { recursive: true })
    .then(() => fs.writeFile(path.join(dir, rel), text));
  const read = (rel) => fs.readFile(path.join(dir, rel), "utf8").catch(() => undefined);
  return { dir, client, engine, write, read };
}

test("dos equipos sincronizan a través de StorageWeb", { skip }, async () => {
  const a = await machine("a"), b = await machine("b");
  const roots = await a.client.roots();
  assert.ok(roots.some((r) => r.name === "home"), "la carpeta personal aparece en /dav/");
  await a.client.mkdirs("home/proyecto");

  // A crea un proyecto (con carpetas, acentos y espacios) y lo sube; B lo baja
  await a.write("src/app.js", "console.log(1)");
  await a.write("docs/léeme ñ.md", "hola");
  await a.write("node_modules/x/index.js", "no se sube");
  let s = await a.engine.run();
  assert.equal(s.uploaded, 2);
  s = await b.engine.run();
  assert.equal(s.downloaded, 2);
  assert.equal(await b.read("docs/léeme ñ.md"), "hola");
  assert.equal(await b.read("node_modules/x/index.js"), undefined);

  // B guarda un cambio (push con If-Match) y A lo recibe
  await new Promise((r) => setTimeout(r, 20));
  await b.write("src/app.js", "console.log(2)");
  assert.equal(await b.engine.push(["src/app.js"]), true);
  s = await a.engine.run();
  assert.equal(await a.read("src/app.js"), "console.log(2)");

  // Los dos cambian el mismo archivo: A lo sube primero; B no lo pisa y queda como conflicto
  await new Promise((r) => setTimeout(r, 20));
  await a.write("src/app.js", "versión A");
  await b.write("src/app.js", "versión B");
  assert.equal(await a.engine.push(["src/app.js"]), true);
  assert.equal(await b.engine.push(["src/app.js"]), false);   // 412: el servidor cambió
  s = await b.engine.run();
  assert.equal(s.conflicts.length, 1);
  assert.equal(await b.read("src/app.js"), "versión A");
  assert.equal(await b.read(s.conflicts[0].copy), "versión B");
  await a.engine.run();                                         // la copia en conflicto llega también a A
  const aFiles = await a.engine.local.scan();
  assert.ok([...aFiles.keys()].some((k) => k.includes("(conflicto ")), "A recibe la copia en conflicto");

  // A borra una carpeta: B la pierde también
  await fs.rm(path.join(a.dir, "docs"), { recursive: true });
  s = await a.engine.run();
  assert.equal(s.deletedRemote, 1);
  s = await b.engine.run();
  assert.equal(s.deletedLocal, 1);
  assert.equal(await b.read("docs/léeme ñ.md"), undefined);
});

test("contra StorageWeb: una carpeta que contiene la copia del servidor no se sincroniza (bucle)", {
  skip: !(URL && process.env.STORAGEWEB_TEST_DATA) && "sin servidor (STORAGEWEB_TEST_DATA)",
}, async () => {
  const { SyncLoopError } = require("../src/sync");
  const client = new DavClient(URL, process.env.STORAGEWEB_TEST_USER, process.env.STORAGEWEB_TEST_TOKEN);
  await client.mkdirs("home/bucle");
  // La carpeta de datos del servidor, que dentro tiene homes/<usuario>/bucle: como un StorageWeb de pruebas
  // que guarda sus archivos dentro del proyecto que se sincroniza
  const dataDir = process.env.STORAGEWEB_TEST_DATA;
  const engine = new SyncEngine({
    local: new LocalFs(dataDir, excluder([...DEFAULT_EXCLUDES])), remote: client, remoteRoot: "home/bucle",
    store: { load: async () => new Map(), save: async () => undefined },
  });
  await assert.rejects(engine.run({ checkLoop: true }), (err) => {
    assert.ok(err instanceof SyncLoopError, String(err));
    assert.equal(err.localDir, `homes/${process.env.STORAGEWEB_TEST_USER}/bucle`);
    return true;
  });
  assert.deepEqual((await client.list("home/bucle")).map((e) => e.name), [], "no queda nada en el servidor");
});

test("contra StorageWeb: lo oculto en el servidor (storage.hidden) se queda solo en el equipo", {
  skip: !(URL && process.env.STORAGEWEB_TEST_HIDDEN) && "sin servidor con storage.hidden",
}, async () => {
  const m = await machine("oculto");
  // Patrón configurado en el servidor de la prueba: *.oculto
  await m.write("normal.txt", "1");
  await m.write("datos.oculto", "local");
  let s = await m.engine.run();
  assert.deepEqual([s.uploaded, s.hidden, s.errors], [1, 1, []]);
  assert.equal(await m.client.stat("home/proyecto/datos.oculto"), null, "no está en el servidor");
  assert.equal(await m.client.isHidden("home/proyecto/datos.oculto"), true);
  assert.equal(await m.client.isHidden("home/proyecto/no-existe.txt"), false);
  s = await m.engine.run();
  assert.deepEqual([s.uploaded, s.hidden, s.deletedLocal], [0, 0, 0]);
  assert.equal(await m.read("datos.oculto"), "local");
});

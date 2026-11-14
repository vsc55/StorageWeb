// Casos que salieron usando la extensión de verdad: archivos que el servidor no lista, una carpeta que
// contiene la copia del servidor (bucle), parar una pasada larga y las exclusiones tipo .gitignore.
"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");

const { DavError } = require("../src/dav");
const { DEFAULT_EXCLUDES, excluder, ignorePatterns } = require("../src/glob");
const { SyncEngine, SyncLoopError } = require("../src/sync");

let clock = 1000;

class MemLocal {
  constructor() { this.files = new Map(); }
  set(p, text) { this.files.set(p, { data: Buffer.from(text), mtime: ++clock }); }
  text(p) { const f = this.files.get(p); return f ? f.data.toString() : undefined; }
  async scan() { return new Map([...this.files].map(([p, f]) => [p, { size: f.data.length, mtime: f.mtime }])); }
  async stat(p) { const f = this.files.get(p); return f ? { size: f.data.length, mtime: f.mtime } : null; }
  async read(p) { return this.files.get(p).data; }
  async write(p, data) { this.files.set(p, { data: Buffer.from(data), mtime: ++clock }); return this.stat(p); }
  async remove(p) { this.files.delete(p); }
  async rename(p, to) { this.files.set(to, this.files.get(p)); this.files.delete(p); }
}

/** Servidor en memoria. `hidden`: lo que no sale en los listados (como los .archivos antes). `mirror`: dónde
 * aparece en local lo que se sube (la copia del servidor dentro de la carpeta local). */
class MemRemote {
  constructor({ hidden = () => false, mirror = null } = {}) {
    this.files = new Map(); this.version = 0; this.hidden = hidden; this.mirror = mirror; this.puts = 0;
  }
  set(p, text) { this.files.set(`home/w/${p}`, { data: Buffer.from(text), etag: `v${++this.version}` }); }
  text(p) { const f = this.files.get(`home/w/${p}`); return f ? f.data.toString() : undefined; }
  async walk(root, skip) {
    const out = new Map();
    for (const [p, f] of this.files) {
      const rel = p.slice(root.length + 1);
      if (p.startsWith(`${root}/`) && !this.hidden(rel) && !skip(rel, false)) {
        out.set(rel, { path: rel, etag: f.etag, size: f.data.length });
      }
    }
    return out;
  }
  async stat(p) { const f = this.files.get(p); return f ? { path: p, etag: f.etag, size: f.data.length, isDir: false } : null; }
  async get(p) { return this.files.get(p).data; }
  async put(p, data, cond = {}) {
    const cur = this.files.get(p);
    if (cond.ifNoneMatch && cur) throw new DavError(412, "exists");
    if (cond.ifMatch && (!cur || cur.etag !== cond.ifMatch)) throw new DavError(412, "changed");
    this.puts++;
    const etag = `v${++this.version}`;
    this.files.set(p, { data: Buffer.from(data), etag });
    if (this.mirror) this.mirror.local.set(this.mirrored(p), data.toString());
    return etag;
  }
  async remove(p) {
    this.files.delete(p);
    if (this.mirror) this.mirror.local.files.delete(this.mirrored(p));
  }
  async mkdirs() {}
  mirrored(p) { const rel = p.slice("home/w/".length); return this.mirror.dir ? `${this.mirror.dir}/${rel}` : rel; }
}

function setup(remoteOptions) {
  const local = new MemLocal(), remote = new MemRemote(remoteOptions);
  let saved = new Map(), saves = 0;
  const store = { load: async () => new Map(saved), save: async (s) => { saved = new Map(s); saves++; } };
  const engine = new SyncEngine({ local, remote, remoteRoot: "home/w", store, conflictLabel: "conflicto" });
  return { local, remote, engine, state: () => saved, saves: () => saves };
}

test("lo que el servidor tiene pero no lista no se da por borrado: se compara en vez de fallar", async () => {
  const { local, remote, engine, state } = setup({ hidden: (rel) => rel.startsWith(".") });
  local.set(".gitignore", "igual");
  local.set(".env", "mío");
  remote.set(".gitignore", "igual");
  remote.set(".env", "suyo");
  const s = await engine.run();
  assert.deepEqual(s.errors, [], "sin errores 412");
  assert.ok(state().has(".gitignore"), "igual en los dos: queda sincronizado");
  assert.equal(s.conflicts.length, 1, "distinto: conflicto, se guardan los dos");
  assert.equal(local.text(".env"), "suyo");
  assert.ok([...local.files.keys()].some((k) => k.startsWith(".env (conflicto ")));
});

test("bucle: la carpeta local contiene la copia del servidor → no se sincroniza nada", async () => {
  const local = new MemLocal();
  const { remote, engine } = setup({ mirror: { local, dir: ".dev/shared/w" } });
  engine.local = local;
  local.set("src/a.py", "x");
  await assert.rejects(engine.run({ checkLoop: true }), (err) => {
    assert.ok(err instanceof SyncLoopError);
    assert.equal(err.localDir, ".dev/shared/w");
    return true;
  });
  assert.equal(remote.files.size, 0, "la prueba se borra y no se sube nada");
  assert.ok(![...local.files.keys()].some((k) => k.includes(".storageweb-probe-")));

  // Con esa carpeta excluida ya no hay bucle
  const skip = excluder(ignorePatterns("/.dev/shared/w/").patterns);
  const ok = new SyncEngine({ local, remote, remoteRoot: "home/w", skip, conflictLabel: "c",
    store: { load: async () => new Map(), save: async () => undefined } });
  local.scan = async () => new Map([...local.files].filter(([p]) => !skip(p))
    .map(([p, f]) => [p, { size: f.data.length, mtime: f.mtime }]));
  const s = await ok.run({ checkLoop: true });
  assert.equal(s.uploaded, 1);
});

test("bucle: la carpeta local es la misma que la del servidor", async () => {
  const local = new MemLocal();
  const { engine } = setup({ mirror: { local, dir: "" } });
  engine.local = local;
  await assert.rejects(engine.run({ checkLoop: true }), (err) => err instanceof SyncLoopError && err.localDir === "");
});

test("cancelar para la pasada en curso y guarda lo hecho; las pasadas largas guardan por el camino", async () => {
  const { local, remote, engine, state, saves } = setup();
  for (let i = 0; i < 450; i++) local.set(`f${String(i).padStart(3, "0")}.txt`, `${i}`);
  const put = remote.put.bind(remote);
  remote.put = async (...args) => {
    const etag = await put(...args);
    if (remote.puts === 300) engine.cancel();
    return etag;
  };
  await engine.run();
  assert.equal(remote.puts, 300, "para en cuanto se cancela");
  assert.equal(state().size, 300, "lo subido queda apuntado");
  assert.ok(saves() >= 2, "guardó durante la pasada, no solo al final");
});

test("exclusiones: las de siempre y el formato de .gitignore", () => {
  const skip = excluder(DEFAULT_EXCLUDES);
  for (const p of [".venv", ".venv/Lib/x.py", "a/venv/bin/python", "src/__pycache__/m.cpython-314.pyc", "m.pyc",
    ".git/HEAD", "web/node_modules/x/i.js", ".pytest_cache/v/x"]) {
    assert.ok(skip(p, p === ".venv"), p);
  }
  for (const p of ["src/app.py", ".gitignore", ".storagewebignore", "docs/venv.md", "pyc.txt"]) assert.ok(!skip(p), p);

  const { patterns, unsupported } = ignorePatterns([
    "# comentario", "", "/.dev/", "dist/", "*.log", "build", "docs/tmp/*.bak", "!importante.log", "\\#raro",
  ].join("\n"));
  assert.deepEqual(unsupported, ["!importante.log"]);
  const ig = excluder(patterns);
  assert.ok(ig(".dev", true) && ig(".dev/data/storageweb.db"));
  assert.ok(!ig("sub/.dev/x"), "/.dev/ solo en la raíz");
  assert.ok(ig("dist", true) && ig("a/dist/x.js"), "dist/ en cualquier sitio");
  assert.ok(ig("x.log") && ig("a/b/x.log"));
  assert.ok(ig("build") && ig("a/build/x"));
  assert.ok(ig("docs/tmp/a.bak") && !ig("x/docs/tmp/a.bak"));
  assert.ok(ig("#raro"));
  assert.ok(!ig("src/app.py"));
});

test("oculto en el servidor (storage.hidden): no se sube ni se borra aquí, y no se reintenta en cada pasada", async () => {
  const { local, remote, engine, state } = setup();
  const hidden = (p) => p.endsWith(".oculto");
  const put = remote.put.bind(remote);
  let refused = 0;
  remote.put = async (p, data, cond) => {
    if (hidden(p)) { refused++; throw new DavError(403, "hidden", true); }
    return put(p, data, cond);
  };
  remote.isHidden = async (p) => hidden(p);
  local.set("normal.txt", "1");
  local.set("nota.oculto", "solo aquí");
  let s = await engine.run();
  assert.deepEqual([s.uploaded, s.hidden, s.errors.length], [1, 1, 0]);
  assert.ok(state().get("nota.oculto").hidden);
  s = await engine.run();
  assert.equal(refused, 1, "no se reintenta");
  assert.equal(local.text("nota.oculto"), "solo aquí");

  // Algo que ya estaba sincronizado y el administrador oculta después: no se borra aquí
  remote.set("antes.oculto", "v");
  local.set("antes.oculto", "v");
  const saved = state();
  saved.set("antes.oculto", { size: 1, mtime: local.files.get("antes.oculto").mtime, etag: "x" });
  engine.store.save(saved);
  remote.files.delete("home/w/antes.oculto");  // ya no sale en el listado
  s = await engine.run({ maxDeletes: 0, confirmDeletes: async () => assert.fail("no debe preguntar por borrados") });
  assert.equal(local.text("antes.oculto"), "v");
  assert.equal(s.deletedLocal, 0);
});

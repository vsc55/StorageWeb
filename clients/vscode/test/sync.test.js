// Motor de sincronización con un disco y un servidor en memoria: node --test clients/vscode/test
"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");

const { DavError, parseMultistatus } = require("../src/dav");
const { excluder, DEFAULT_EXCLUDES } = require("../src/glob");
const { SyncEngine, conflictName, plan } = require("../src/sync");

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

class MemRemote {
  constructor() { this.files = new Map(); this.version = 0; this.puts = []; }
  set(p, text) { this.files.set(`home/w/${p}`, { data: Buffer.from(text), etag: `v${++this.version}` }); }
  text(p) { const f = this.files.get(`home/w/${p}`); return f ? f.data.toString() : undefined; }
  async walk(root, skip) {
    const out = new Map();
    for (const [p, f] of this.files) {
      if (!p.startsWith(`${root}/`)) continue;
      const rel = p.slice(root.length + 1);
      if (!skip(rel, false)) out.set(rel, { path: rel, etag: f.etag, size: f.data.length });
    }
    return out;
  }
  async get(p) { return this.files.get(p).data; }
  async put(p, data, cond = {}) {
    const cur = this.files.get(p);
    if (cond.ifNoneMatch && cur) throw new DavError(412, "exists");
    if (cond.ifMatch && (!cur || cur.etag !== cond.ifMatch)) throw new DavError(412, "changed");
    this.puts.push(p);
    const etag = `v${++this.version}`;
    this.files.set(p, { data: Buffer.from(data), etag });
    return etag;
  }
  async remove(p, cond = {}) {
    const cur = this.files.get(p);
    if (cond.ifMatch && cur && cur.etag !== cond.ifMatch) throw new DavError(412, "changed");
    this.files.delete(p);
  }
  async mkdirs() {}
}

function setup() {
  const local = new MemLocal(), remote = new MemRemote();
  let saved = new Map();
  const store = { load: async () => new Map(saved), save: async (s) => { saved = new Map(s); } };
  const engine = new SyncEngine({ local, remote, remoteRoot: "home/w", store, conflictLabel: "conflicto" });
  return { local, remote, engine, state: () => saved };
}

test("primera sincronización: sube lo local, baja lo remoto y los iguales no hacen nada", async () => {
  const { local, remote, engine } = setup();
  local.set("a.txt", "local");
  local.set("igual.txt", "lo mismo");
  remote.set("b/c.txt", "remoto");
  remote.set("igual.txt", "lo mismo");
  const s = await engine.run();
  assert.equal(remote.text("a.txt"), "local");
  assert.equal(local.text("b/c.txt"), "remoto");
  assert.deepEqual([s.uploaded, s.downloaded, s.conflicts.length], [1, 1, 0]);
  const again = await engine.run();  // segunda vez: nada que hacer
  assert.deepEqual([again.uploaded, again.downloaded], [0, 0]);
});

test("cambios en un lado, borrados y conflicto (se guardan las dos versiones)", async () => {
  const { local, remote, engine } = setup();
  local.set("x.txt", "1");
  local.set("y.txt", "1");
  local.set("z.txt", "1");
  local.set("c.txt", "base");
  await engine.run();
  local.set("x.txt", "2 local");           // cambia aquí
  remote.set("y.txt", "2 remoto");         // cambia allí
  local.files.delete("z.txt");             // se borra aquí
  local.set("c.txt", "mía");               // cambia en los dos
  remote.set("c.txt", "suya");
  const s = await engine.run();
  assert.equal(remote.text("x.txt"), "2 local");
  assert.equal(local.text("y.txt"), "2 remoto");
  assert.equal(remote.text("z.txt"), undefined);
  assert.equal(local.text("c.txt"), "suya");
  const copy = s.conflicts[0].copy;
  assert.match(copy, /^c \(conflicto \d{4}-\d\d-\d\d \d{4}\)\.txt$/);
  assert.equal(local.text(copy), "mía");
  assert.equal(remote.text(copy), "mía");  // la copia también llega al servidor
  remote.files.delete("home/w/x.txt");     // se borra allí
  await engine.run();
  assert.equal(local.text("x.txt"), undefined);
});

test("borrados masivos: se pregunta y, si no se confirman, se recupera en vez de borrar", async () => {
  const { local, remote, engine } = setup();
  for (let i = 0; i < 15; i++) local.set(`f${i}.txt`, "x");
  await engine.run();
  local.files.clear();  // p. ej. se vació la carpeta por error
  let asked = 0;
  const s = await engine.run({ confirmDeletes: async (n) => { asked = n; return false; } });
  assert.equal(asked, 15);
  assert.equal(s.deletedRemote, 0);
  assert.equal(local.files.size, 15);  // recuperados del servidor
  assert.equal(remote.files.size, 15);
});

test("push al guardar: sube con If-Match y, si el servidor cambió, pide sincronización completa", async () => {
  const { local, remote, engine } = setup();
  local.set("a.txt", "1");
  await engine.run();
  local.set("a.txt", "2");
  assert.equal(await engine.push(["a.txt"]), true);
  assert.equal(remote.text("a.txt"), "2");
  remote.set("a.txt", "remoto");           // otro lo cambia
  local.set("a.txt", "3");
  assert.equal(await engine.push(["a.txt"]), false);
  assert.equal(remote.text("a.txt"), "remoto");  // no se pisó
  const s = await engine.run();
  assert.equal(s.conflicts.length, 1);
  local.files.delete("a.txt");
  assert.equal(await engine.push(["a.txt"]), true);
  assert.equal(remote.text("a.txt"), undefined);
});

test("sin cuota en el servidor (507): se para y se dice por qué", async () => {
  const { local, remote, engine } = setup();
  local.set("a.txt", "a");
  local.set("b.txt", "b");
  local.set("c.txt", "c");
  remote.put = async () => { throw new DavError(507, "PUT", false, "No hay cuota suficiente en «Mi carpeta»"); };
  const summary = await engine.run();
  assert.equal(summary.uploaded, 0);
  assert.equal(summary.errors.length, 1);                      // no lo intenta con todos
  assert.equal(summary.noSpace, "No hay cuota suficiente en «Mi carpeta»");
});

test("plan: tabla de decisiones", () => {
  const L = (size, mtime) => ({ size, mtime }), R = (etag) => ({ etag }), S = (size, mtime, etag) => ({ size, mtime, etag });
  const p = plan(
    new Map([["sube", L(1, 2)], ["igual", L(1, 1)], ["borrado-alli", L(1, 1)], ["nuevo-aqui", L(1, 1)]]),
    new Map([["baja", R("e2")], ["igual", R("e1")], ["borrado-aqui", R("e1")], ["nuevo-alli", R("e1")]]),
    new Map([["sube", S(1, 1, "e1")], ["baja", S(1, 1, "e1")], ["igual", S(1, 1, "e1")],
      ["borrado-alli", S(1, 1, "e1")], ["borrado-aqui", S(1, 1, "e1")], ["en-ningun-sitio", S(1, 1, "e1")]]));
  assert.deepEqual(Object.fromEntries(p.map((a) => [a.path, a.type])), {
    "sube": "upload", "baja": "download", "borrado-alli": "deleteLocal", "borrado-aqui": "deleteRemote",
    "nuevo-aqui": "upload", "nuevo-alli": "download", "en-ningun-sitio": "forget",
  });
});

test("exclusiones y nombres de conflicto", () => {
  const skip = excluder([...DEFAULT_EXCLUDES, "dist/**", "*.log"]);
  assert.ok(skip("node_modules", true) && skip("a/node_modules/x.js") && skip(".git", true));
  assert.ok(skip("dist", true) && skip("error.log") && skip("~$informe.docx") && skip("a/.DS_Store"));
  assert.ok(!skip("src/app.js") && !skip("docs/log.md"));
  assert.equal(conflictName("a/informe.docx", "conflicto", new Date(2026, 10, 14, 18, 5)),
    "a/informe (conflicto 2026-11-14 1805).docx");
  assert.equal(conflictName("Makefile", "conflict", new Date(2026, 0, 2, 3, 4)), "Makefile (conflict 2026-01-02 0304)");
});

test("parseMultistatus: prefijos, entidades, códigos de escape y propstat 404", () => {
  const xml = `<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">
    <D:response><D:href>/dav/home/w/</D:href><D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop>
      <D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>
    <D:response><D:href>https://x/dav/home/w/a%C3%B1o%20%26%20m%C3%A1s.txt</D:href><D:propstat><D:prop>
      <D:resourcetype/><D:getcontentlength>12</D:getcontentlength><D:getetag>"123-12"</D:getetag>
      <D:getlastmodified>Fri, 13 Nov 2026 10:00:00 GMT</D:getlastmodified></D:prop>
      <D:status>HTTP/1.1 200 OK</D:status></D:propstat>
      <D:propstat><D:prop><D:quota/></D:prop><D:status>HTTP/1.1 404 Not Found</D:status></D:propstat></D:response>
  </D:multistatus>`;
  const [dir, file] = parseMultistatus(xml, "/dav/");
  assert.deepEqual([dir.path, dir.isDir], ["home/w", true]);
  assert.deepEqual([file.path, file.name, file.size, file.etag, file.isDir],
    ["home/w/año & más.txt", "año & más.txt", 12, "123-12", false]);
  assert.ok(file.mtime > 0);
  assert.throws(() => parseMultistatus('<!DOCTYPE x [<!ENTITY a "b">]><x/>', "/dav/"));
});

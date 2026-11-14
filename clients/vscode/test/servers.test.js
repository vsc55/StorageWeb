// La lista de servidores (servers.js) y las partes de remotefs.js que no necesitan servidor.
"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");

const { DavError } = require("../src/dav");
const { RemoteFs, RemoteFsError, cleanPath, translate } = require("../src/remotefs");
const { ServerStore, normalizeUrl, secretKey } = require("../src/servers");

function memory() {
  const state = new Map(), secrets = new Map();
  return {
    state, secrets,
    store: new ServerStore(
      { get: (k) => state.get(k), update: async (k, v) => { state.set(k, JSON.parse(JSON.stringify(v))); } },
      { get: async (k) => secrets.get(k), store: async (k, v) => { secrets.set(k, v); }, delete: async (k) => { secrets.delete(k); } }),
  };
}

test("normalizeUrl: solo http/https, sin barra final ni credenciales", () => {
  assert.equal(normalizeUrl(" https://Files.Example.com/ "), "https://files.example.com");
  assert.equal(normalizeUrl("http://host:8080/archivos//"), "http://host:8080/archivos");
  assert.equal(normalizeUrl("https://host:443"), "https://host");
  for (const bad of ["", "files.example.com", "ftp://host", "javascript:alert(1)", "https://u:p@host", "https://host/?a=1"]) {
    assert.equal(normalizeUrl(bad), null, bad);
  }
});

test("varios servidores: añadir, buscar, renombrar, cambiar de dirección y quitar", async () => {
  const { store, secrets } = memory();
  const a = await store.add({ url: "https://files.example.com/", username: "Ana" }, "sw_a");
  const b = await store.add({ url: "https://otro.example.com", username: "ana", label: "Casa" }, "sw_b");
  assert.equal(store.list().length, 2);
  assert.deepEqual(store.list().map((p) => store.title(p)), ["Casa", "files.example.com"]);
  assert.equal(store.find("https://FILES.example.com", "ana").id, a.id, "dirección y usuario sin distinguir mayúsculas");
  assert.equal(await store.token(a), "sw_a");
  // la misma clave que usaban las carpetas sincronizadas antes del panel
  assert.equal(secrets.get(secretKey("https://files.example.com", "Ana")), "sw_a");

  // Añadir otra vez el mismo servidor y usuario: no se duplica, se actualiza el token
  const again = await store.add({ url: "https://files.example.com", username: "ana" }, "sw_a2");
  assert.equal(again.id, a.id);
  assert.equal(store.list().length, 2);
  assert.equal(await store.token(a), "sw_a2");

  await store.update(a.id, { label: "Trabajo" });
  assert.equal(store.title(store.get(a.id)), "Trabajo");

  // Cambiar la dirección: el token pasa a la clave nueva
  const moved = await store.update(a.id, { url: "https://nuevo.example.com" });
  assert.equal(moved.url, "https://nuevo.example.com");
  assert.equal(await store.token(moved), "sw_a2");
  assert.equal(secrets.get(secretKey("https://files.example.com", "Ana")), undefined);
  await assert.rejects(store.update(a.id, { url: "https://otro.example.com" }), /already/, "no se pisa otro servidor");
  await assert.rejects(store.update(a.id, { url: "no es una url" }), /Invalid/);

  await store.remove(b.id);
  assert.equal(store.list().length, 1);
  assert.equal(await store.token(b), undefined, "el token se borra al quitarlo");
  await assert.rejects(store.add({ url: "ftp://x", username: "y" }), /Invalid/);
  await assert.rejects(store.add({ url: "https://x", username: " " }), /user/);
});

test("remotefs: rutas limpias y errores de WebDAV con los códigos de VS Code", async () => {
  assert.equal(cleanPath("/home/a//b.txt/"), "home/a/b.txt");
  assert.equal(cleanPath("/"), "");
  for (const bad of ["/home/../etc", "/home/./a", "/home/a\\..\\b"]) {
    assert.throws(() => cleanPath(bad), (e) => e instanceof RemoteFsError && e.code === "NoPermissions", bad);
  }
  const code = (status, op) => translate(new DavError(status, "x"), "p", op).code;
  assert.equal(code(404), "FileNotFound");
  assert.equal(code(409), "FileNotFound");
  assert.equal(code(412), "Conflict");
  assert.equal(code(412, "FileExists"), "FileExists");
  assert.equal(code(403), "NoPermissions");
  assert.equal(code(401), "NoPermissions");
  assert.equal(code(0), "Unavailable");
  assert.equal(translate(new DavError(500, "boom"), "p") instanceof DavError, true, "otros errores, tal cual");

  // La caché de stat dura poco y se invalida al escribir
  let now = 0, stats = 0;
  const client = {
    stat: async (p) => { stats++; return { path: p, name: p, label: "", isDir: false, size: 1, etag: "e1", mtime: 5 }; },
    put: async () => "e2",
  };
  const fs = new RemoteFs(async () => /** @type {any} */ (client), { ttlMs: 1000, now: () => now });
  assert.deepEqual(await fs.stat("s", "/"), { type: "dir", size: 0, mtime: 0, etag: "" });
  await fs.stat("s", "/home/a.txt");
  await fs.stat("s", "/home/a.txt");
  assert.equal(stats, 1);
  now = 2000;
  await fs.stat("s", "/home/a.txt");
  assert.equal(stats, 2);
  await assert.rejects(fs.writeFile("s", "/home/a.txt", Buffer.from("x"), { create: true, overwrite: false }),
    (e) => e.code === "FileExists");
  assert.equal(await fs.writeFile("s", "/home/a.txt", Buffer.from("x"), { create: false, overwrite: true }), false);
});

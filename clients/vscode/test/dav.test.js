// El cliente WebDAV (dav.js) sin StorageWeb: el motivo de los errores y las descargas cortadas a medias.
"use strict";
const assert = require("node:assert/strict");
const http = require("node:http");
const { test } = require("node:test");

const { DavClient, DavError } = require("../src/dav");

/** Un cliente cuyo `fetch` responde lo que diga `answer(method, url)`. */
function clientWith(answer) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push(`${init.method} ${url}`);
    return answer(init.method, String(url));
  };
  return { client: new DavClient("https://files.example.com", "ana", "sw_x", { fetch: /** @type {any} */ (fetch) }), calls };
}

test("el motivo de StorageWeb (X-StorageWeb-Reason) queda en DavError.code", async () => {
  const cases = [[401, "account_disabled"], [401, "token_expired"], [403, "read_only"], [403, "ip_banned"],
    [503, "maintenance"], [413, "too_large"]];
  for (const [status, code] of cases) {
    const { client } = clientWith(() => new Response(`${status} Error\nNo cabe`, {
      status, headers: { "X-StorageWeb-Reason": code, ...(status === 503 ? { "Retry-After": "30" } : {}) } }));
    await assert.rejects(client.put("home/a.txt", Buffer.from("x")), (err) => {
      assert.ok(err instanceof DavError);
      assert.deepEqual([err.status, err.code, err.path], [status, code, "home/a.txt"]);
      if (status === 413) assert.equal(err.reason, "No cabe", "el texto del motivo, como con el 507");
      return true;
    });
  }
  // Sin cabecera, sin código (401 = credenciales rechazadas, como siempre); un valor raro se limpia
  const { client } = clientWith(() => new Response("", { status: 401 }));
  await assert.rejects(client.roots(), (err) => err.status === 401 && err.code === "");
  const odd = clientWith(() => new Response("", { status: 403, headers: { "X-StorageWeb-Reason": " Read_Only<script> " } }));
  await assert.rejects(odd.client.remove("home/a.txt"), (err) => err.code === "read_onlyscript");
  // La raíz vinculada que ya no está: stat da null (404), sin distinguir si es que ya no hay acceso
  const gone = clientWith(() => new Response("", { status: 404 }));
  assert.equal(await gone.client.stat("compartida/proyecto"), null);
});

test("una descarga con menos bytes de los anunciados o que falla al leer es un error de red, sin datos", async () => {
  const short = clientWith(() => new Response("solo un trozo", { status: 200, headers: { "Content-Length": "1000" } }));
  await assert.rejects(short.client.download("home/a.txt"), (err) => {
    assert.ok(err instanceof DavError);
    assert.deepEqual([err.status, err.code], [0, "interrupted"]);
    assert.match(err.message, /13 of 1000 bytes/);
    return true;
  });
  const broken = clientWith(() => new Response(new ReadableStream({
    start(c) { c.enqueue(new TextEncoder().encode("un poco")); c.error(new Error("socket hang up")); },
  }), { status: 200 }));
  await assert.rejects(broken.client.get("home/a.txt"), (err) => err.status === 0 && err.code === "interrupted");
  // Un listado cortado, igual (nunca un listado a medias que haría creer que faltan archivos)
  const listing = clientWith(() => new Response("<d:multistatus", { status: 207, headers: { "Content-Length": "5000" } }));
  await assert.rejects(listing.client.list("home"), (err) => err.status === 0 && err.code === "interrupted");
  // Completa: se acepta; comprimida, Content-Length es lo que ocupa comprimida (fetch la descomprime): no se compara
  const ok = clientWith(() => new Response("hola", { status: 200, headers: { ETag: '"v1"', "Content-Length": "4" } }));
  assert.deepEqual(await ok.client.download("home/a.txt"), { data: Buffer.from("hola"), etag: "v1" });
  const gzip = clientWith(() => new Response("hola", { status: 200,
    headers: { ETag: '"v2"', "Content-Length": "2", "Content-Encoding": "gzip" } }));
  assert.deepEqual(await gzip.client.download("home/a.txt"), { data: Buffer.from("hola"), etag: "v2" });
});

test("el servidor corta la conexión a mitad de la descarga (fetch de verdad)", async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "Content-Length": "100000", "Content-Type": "application/octet-stream" });
    res.write(Buffer.alloc(1000, 65));
    setTimeout(() => res.socket.destroy(), 20);  // como al desactivar la cuenta o perder el acceso a mitad
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = /** @type {import("node:net").AddressInfo} */ (server.address());
  try {
    const client = new DavClient(`http://127.0.0.1:${port}`, "ana", "sw_x");
    await assert.rejects(client.download("home/grande.bin"), (err) => {
      assert.ok(err instanceof DavError, String(err));
      assert.deepEqual([err.status, err.code], [0, "interrupted"]);
      return true;
    });
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});

// Iniciar sesión en el navegador (src/connect.js): la petición, el canje y, contra un StorageWeb de verdad,
// el flujo completo con un «navegador» de prueba (test/browser.js).
"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { test } = require("node:test");

const { ConnectError, challengeOf, exchange, parseCallback, startRequest } = require("../src/connect");
const { DavClient } = require("../src/dav");
const { browserSession } = require("./browser");

const URL_ = process.env.STORAGEWEB_TEST_URL;
const PASSWORD = process.env.STORAGEWEB_TEST_PASSWORD;
const skip = !(URL_ && PASSWORD) && "sin servidor (STORAGEWEB_TEST_URL y STORAGEWEB_TEST_PASSWORD)";
const CALLBACK = "vscode://storageweb.storageweb-sync/auth";

test("startRequest: PKCE (SHA-256 del verifier), state y vuelta a VS Code", () => {
  const a = startRequest("https://files.example.com/", CALLBACK, "PORTÁTIL 1");
  const b = startRequest("https://files.example.com", CALLBACK, "x");
  const url = new URL(a.url);
  assert.equal(url.origin + url.pathname, "https://files.example.com/connect/vscode");
  assert.equal(url.searchParams.get("redirect_uri"), CALLBACK);
  assert.equal(url.searchParams.get("state"), a.state);
  assert.equal(url.searchParams.get("device"), "PORTÁTIL 1");
  const expected = crypto.createHash("sha256").update(a.verifier).digest("base64url");
  assert.equal(url.searchParams.get("challenge"), expected);
  assert.equal(challengeOf(a.verifier), expected);
  assert.ok(!a.url.includes(a.verifier), "el verifier no sale del equipo");
  assert.ok(a.verifier.length >= 43 && a.state.length >= 16);
  assert.notEqual(a.verifier, b.verifier);
  assert.notEqual(a.state, b.state);
  assert.deepEqual(parseCallback("code=abc&state=xyz"), { code: "abc", state: "xyz", error: "" });
  assert.deepEqual(parseCallback("error=access_denied&state=xyz"), { code: "", state: "xyz", error: "access_denied" });
});

test("exchange: respuestas del servidor", async () => {
  const reply = (status, body) => async (url, init) => {
    assert.equal(url, "https://h/connect/token");
    assert.deepEqual(JSON.parse(init.body), { code: "c", verifier: "v" });
    return new Response(JSON.stringify(body), { status });
  };
  const ok = await exchange("https://h/", "c", "v", { fetch: reply(200, { username: "ana", token: "sw_x", name: "VS Code", days: 30 }) });
  assert.deepEqual(ok, { username: "ana", token: "sw_x", name: "VS Code", days: 30 });
  const code = (status) => (err) => err instanceof ConnectError && err.code === status;
  await assert.rejects(exchange("https://h", "c", "v", { fetch: reply(400, { error: "invalid_grant" }) }), code("invalid_grant"));
  await assert.rejects(exchange("https://h", "c", "v", { fetch: reply(404, {}) }), code("unsupported"));
  await assert.rejects(exchange("https://h", "c", "v", { fetch: reply(403, {}) }), code("tokens_disabled"));
  await assert.rejects(exchange("https://h", "c", "v", { fetch: reply(200, { nada: 1 }) }), code("invalid_grant"));
  await assert.rejects(exchange("https://h", "c", "v", { fetch: async () => { throw new Error("ECONNREFUSED"); } }), code("network"));
});

test("contra StorageWeb: iniciar sesión en el navegador, aceptar y canjear", { skip }, async () => {
  const browser = await browserSession(URL_, process.env.STORAGEWEB_TEST_USER, PASSWORD);
  const request = startRequest(URL_, CALLBACK, "equipo-de-prueba");
  const back = new URL(await browser.authorize(request.url));
  assert.equal(`${back.protocol}//${back.host}${back.pathname}`, CALLBACK);
  const { code, state } = parseCallback(back.search.slice(1));
  assert.equal(state, request.state);
  const got = await exchange(URL_, code, request.verifier);
  assert.equal(got.username, process.env.STORAGEWEB_TEST_USER);
  assert.equal(got.name, "Visual Studio Code (equipo-de-prueba)");
  const roots = await new DavClient(URL_, got.username, got.token).roots();
  assert.ok(roots.some((r) => r.name === "home"), "el token sirve para la unidad de red");
  await assert.rejects(exchange(URL_, code, request.verifier), (e) => e.code === "invalid_grant", "un solo uso");

  // Otro programa que capture la vuelta no tiene el verifier
  const other = startRequest(URL_, CALLBACK, "x");
  const stolen = parseCallback(new URL(await browser.authorize(other.url)).search.slice(1));
  await assert.rejects(exchange(URL_, stolen.code, startRequest(URL_, CALLBACK, "y").verifier), (e) => e.code === "invalid_grant");

  // Cancelar en el navegador
  const denied = startRequest(URL_, CALLBACK, "x");
  assert.equal(parseCallback(new URL(await browser.authorize(denied.url, "deny")).search.slice(1)).error, "access_denied");
});

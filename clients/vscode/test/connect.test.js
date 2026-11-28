// Iniciar sesión en el navegador (src/connect.js): la petición, el canje y, contra un StorageWeb de verdad,
// el flujo completo con un «navegador» de prueba (test/browser.js). Y entrar con la cuenta del equipo
// (`/connect/desktop`): los métodos que anuncia el servidor y el canje del token de Microsoft.
"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { test } = require("node:test");

const {
  ConnectError, challengeOf, desktopMethods, exchange, methodPin, parseCallback, redeemDesktop, secureServer,
  sessionScopes, startRequest,
} = require("../src/connect");
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

const ENTRA = { key: "entra", label: "Microsoft Entra ID", provider: "microsoft", tenant: "11111111-2222-3333-4444-555555555555",
  scopes: ["api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/access_as_user"] };

test("desktopMethods: lo que anuncia el servidor; un servidor antiguo, sin red o raro: ninguno", async () => {
  const reply = (status, body) => async (url, init) => {
    assert.equal(url, "https://h/connect/desktop");
    assert.equal(init.method, "GET");
    assert.ok(!("Authorization" in init.headers), "sin credenciales");
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
  };
  assert.deepEqual(await desktopMethods("https://h/", { fetch: reply(200, { methods: [ENTRA] }) }), [ENTRA]);
  assert.deepEqual(await desktopMethods("https://h", { fetch: reply(200, { methods: [] }) }), []);
  assert.deepEqual(await desktopMethods("https://h", { fetch: reply(404, "<html>Not found</html>") }), []);
  assert.deepEqual(await desktopMethods("https://h", { fetch: reply(200, "no es JSON") }), []);
  assert.deepEqual(await desktopMethods("https://h", { fetch: reply(200, { methods: "x" }) }), []);
  assert.deepEqual(await desktopMethods("https://h", { fetch: async () => { throw new Error("ECONNREFUSED"); } }), []);
  // Los que no traen lo necesario se descartan; sin etiqueta, la clave
  const odd = await desktopMethods("https://h", { fetch: reply(200, { methods: [
    { key: "entra", provider: "microsoft", scopes: [] }, { key: "x", provider: "microsoft", scopes: [1] },
    { provider: "microsoft", scopes: ["s"] }, { key: "otro", provider: "github", scopes: ["s"] },
  ] }) });
  assert.deepEqual(odd, []);
  const bare = await desktopMethods("https://h", { fetch: reply(200, { methods: [{ ...ENTRA, label: "", tenant: "" }] }) });
  assert.deepEqual(bare, [{ ...ENTRA, label: "entra", tenant: "" }]);
});

test("desktopMethods: un servidor malicioso no elige qué token de Microsoft se pide (y se le manda)", async () => {
  const reply = (methods) => async () => new Response(JSON.stringify({ methods }), { status: 200 });
  const evil = [
    ["https://graph.microsoft.com/Mail.Read"],                              // otro recurso: el correo
    ["https://graph.microsoft.com/.default"],
    [`api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/access_as_user`, "offline_access"],     // más de uno
    [`api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/access_as_user`, "VSCODE_CLIENT_ID:00000000-0000-0000-0000-000000000000"],
    ["VSCODE_CLIENT_ID:00000000-0000-0000-0000-000000000000"],
    [`api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/Files.ReadWrite`],                      // otro permiso
    ["api://otra-cosa/access_as_user"],                                     // no es un client id
    [`api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/access_as_user `],
  ];
  for (const scopes of evil) {
    assert.deepEqual(await desktopMethods("https://h", { fetch: reply([{ ...ENTRA, scopes }]) }), [], scopes.join(" "));
  }
  for (const tenant of ["x VSCODE_CLIENT_ID:1", "a:b", "../x", "t-1", 7]) {
    assert.deepEqual(await desktopMethods("https://h", { fetch: reply([{ ...ENTRA, tenant }]) }), [], String(tenant));
  }
  for (const tenant of ["contoso.onmicrosoft.com", "organizations", "11111111-2222-3333-4444-555555555555"]) {
    assert.equal((await desktopMethods("https://h", { fetch: reply([{ ...ENTRA, tenant }]) })).length, 1, tenant);
  }
});

test("secureServer y methodPin: solo HTTPS o el propio equipo; la huella, aplicación y tenant", () => {
  for (const ok of ["https://h", "http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"]) {
    assert.ok(secureServer(ok), ok);
  }
  for (const bad of ["http://h", "http://files.example.com", "ftp://h", "no es una dirección"]) {
    assert.ok(!secureServer(bad), bad);
  }
  assert.equal(methodPin(ENTRA), `${ENTRA.scopes[0]}|${ENTRA.tenant}`);
  assert.notEqual(methodPin(ENTRA), methodPin({ ...ENTRA, tenant: "organizations" }));
});

test("sessionScopes: el inquilino con VSCODE_TENANT, salvo organizations/common", () => {
  assert.deepEqual(sessionScopes(ENTRA), ["api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/access_as_user", "VSCODE_TENANT:11111111-2222-3333-4444-555555555555"]);
  for (const tenant of ["organizations", "common", "Organizations", ""]) {
    assert.deepEqual(sessionScopes({ ...ENTRA, tenant }), ["api://aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/access_as_user"], tenant);
  }
  assert.ok(!sessionScopes(ENTRA).some((s) => s.startsWith("VSCODE_CLIENT_ID")), "con la aplicación de VS Code");
});

test("redeemDesktop: el canje y cada error del servidor", async () => {
  const reply = (status, body) => async (url, init) => {
    assert.equal(url, "https://h/connect/desktop");
    assert.equal(init.method, "POST");
    assert.equal(init.headers["Accept-Language"], "es");
    assert.deepEqual(JSON.parse(init.body), { method: "entra", client: "vscode", access_token: "ms-tok", device: "PC-ANA" });
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
  };
  const call = (status, body) => redeemDesktop("https://h/", ENTRA, "ms-tok", "PC-ANA", { fetch: reply(status, body), language: "es" });
  assert.deepEqual(await call(200, { username: "ana", token: "sw_x", name: "Visual Studio Code (PC-ANA)", days: 365 }),
    { username: "ana", token: "sw_x", name: "Visual Studio Code (PC-ANA)", days: 365 });
  const fails = (code, message = "", serverMessage = message) => (err) => {
    assert.ok(err instanceof ConnectError);
    assert.equal(err.code, code);
    assert.equal(err.serverMessage, serverMessage);
    if (message) assert.equal(err.message, message);
    return true;
  };
  await assert.rejects(call(403, { error: "denied", message: "No estás en los grupos permitidos." }),
    fails("denied", "No estás en los grupos permitidos."));
  await assert.rejects(call(401, { error: "invalid_token", message: "El token no vale." }), fails("invalid_token", "El token no vale."));
  await assert.rejects(call(403, { error: "tokens_disabled" }), fails("tokens_disabled", "API tokens are disabled on this StorageWeb", ""));
  await assert.rejects(call(404, { error: "not_enabled" }), fails("not_enabled", "", ""));
  await assert.rejects(call(400, { error: "unknown_client" }), fails("unknown_client", "", ""));
  // Sin JSON (un servidor antiguo, un proxy): por el estado
  await assert.rejects(call(404, "<html>Not found</html>"), fails("not_enabled", "", ""));
  await assert.rejects(call(401, ""), fails("invalid_token", "", ""));
  await assert.rejects(call(403, ""), fails("denied", "", ""));
  await assert.rejects(call(500, "boom"), fails("failed", "The server did not accept the sign-in (HTTP 500)", ""));
  await assert.rejects(call(200, { nada: 1 }), fails("failed", "", ""));
  await assert.rejects(redeemDesktop("https://h", ENTRA, "t", "d", { fetch: async () => { throw new Error("ECONNREFUSED"); } }),
    fails("network", "Cannot connect to the server: ECONNREFUSED", ""));
});

test("contra StorageWeb: /connect/desktop responde (y un token de Microsoft falso no entra)", { skip }, async () => {
  const methods = await desktopMethods(URL_);
  assert.ok(Array.isArray(methods));
  await assert.rejects(redeemDesktop(URL_, methods[0] || ENTRA, "no-es-un-token", "equipo-de-prueba"),
    (e) => e instanceof ConnectError && ["not_enabled", "invalid_token"].includes(e.code), "sin token de API");
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

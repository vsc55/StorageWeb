// Passkeys en un navegador de verdad: static/js/passkeys.js con navigator.credentials y un autenticador virtual
// (CDP WebAuthn), de añadirla en Mi perfil a entrar con ella. En http://localhost (STORAGEWEB_TEST_LOCALHOST_URL),
// que es lo que el servidor tiene en network.public_url: el único origen sin HTTPS donde el navegador las admite.
import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { findBrowser, launch, sleep } from "../../tools/cdp.mjs";

const BASE = process.env.STORAGEWEB_TEST_LOCALHOST_URL;
const PASSWORD = process.env.STORAGEWEB_TEST_PASSWORD;
let page;

before(async () => {
  page = await launch(process.env.STORAGEWEB_BROWSER || findBrowser());
  await page.send("WebAuthn.enable");
  await page.send("WebAuthn.addVirtualAuthenticator", { options: {
    protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true,
    isUserVerified: true, automaticPresenceSimulation: true } });
});
after(async () => { await page?.close(); });

function noErrors() {
  const found = page.errors.splice(0);
  assert.deepEqual(found, [], "errores en la consola del navegador");
}

/** Espera a que se cumpla ``expression`` aunque la página navegue mientras tanto (el JS redirige al acabar). */
async function until(expression, ms = 15000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try {
      if (await page.evaluate(`!!(${expression})`)) return;
    } catch { /* navegando: el contexto cambia */ }
    await sleep(100);
  }
  const modal = await page.evaluate("document.querySelector('dialog.sw-modal[open]')?.textContent || ''").catch(() => "");
  throw new Error(`No llegó a cumplirse: ${expression} ${modal}`);
}

test("passkeys: se añade en Mi perfil y con ella se entra", async () => {
  await page.login(BASE, "pepa", PASSWORD);
  await page.go(`${BASE}/profile/security`);
  const form = "document.querySelector('form[data-passkey=\"create\"]')";
  await page.waitFor(`${form} && !${form}.hidden`);
  await page.evaluate(`(() => { const f = ${form}; f.passkey_name.value = 'Portátil de pruebas'; f.requestSubmit(); })()`);
  await until("location.pathname === '/profile/mfa/codes' && document.readyState === 'complete'");
  assert.equal(await page.evaluate("document.querySelectorAll('.mfa-recovery code').length"), 10);
  noErrors();

  await page.send("Network.clearBrowserCookies");
  await page.login(BASE, "pepa", PASSWORD);
  assert.equal(await page.evaluate("location.pathname"), "/login/mfa");
  const get = "document.querySelector('form[data-passkey=\"get\"]')";
  await page.waitFor(`${get} && !${get}.hidden`);
  await page.evaluate(`${get}.requestSubmit()`);
  await until("!location.pathname.startsWith('/login') && document.readyState === 'complete'");
  await page.go(`${BASE}/profile/security`);
  assert.match(await page.evaluate("document.querySelector('.passkey-list').textContent"), /Portátil de pruebas/);
  noErrors();
});

test("entrar solo con la passkey: sin usuario ni contraseña", async () => {
  // La del test anterior se guardó en el autenticador (security.passkey_login encendido: credencial residente)
  await page.send("Network.clearBrowserCookies");
  await page.go(`${BASE}/login?manual=1&next=/profile/security`);
  const get = "document.querySelector('form[data-for=\"passwordless\"]')";
  await page.waitFor(`${get} && !${get}.hidden`);
  await page.evaluate(`${get}.requestSubmit()`);
  await until("location.pathname === '/profile/security' && document.readyState === 'complete'");
  assert.match(await page.evaluate("document.querySelector('.passkey-list').textContent"), /Portátil de pruebas/);
  noErrors();
});

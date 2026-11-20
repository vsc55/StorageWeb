// Tests en un navegador de verdad: la administración (buscador Ctrl+K y la barra de guardar de los ajustes). Lo
// lanza tests/integration/test_browser.py contra un servidor real (STORAGEWEB_TEST_URL).
import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { findBrowser, launch } from "../../tools/cdp.mjs";

const BASE = process.env.STORAGEWEB_TEST_URL;
const PASSWORD = process.env.STORAGEWEB_TEST_PASSWORD;
let page;

before(async () => {
  page = await launch(process.env.STORAGEWEB_BROWSER || findBrowser());
  await page.login(BASE, "root", PASSWORD);
});
after(async () => { await page?.close(); });

function noErrors() {
  const found = page.errors.splice(0);
  assert.deepEqual(found, [], "errores en la consola del navegador");
}

test("Ctrl+K abre el buscador de la administración y encuentra ajustes", async () => {
  await page.go(`${BASE}/admin/`);
  await page.press("k", { ctrl: true });
  await page.waitFor("document.getElementById('admin-search').open");
  await page.evaluate(`(() => { const i = document.querySelector('#admin-search input');
                               i.value = 'cuota'; i.dispatchEvent(new Event('input')); })()`);
  await page.waitFor("document.querySelectorAll('#admin-search-results a').length > 0");
  noErrors();
});

test("cambiar un ajuste marca el campo y despierta la barra de guardar", async () => {
  await page.go(`${BASE}/admin/settings/storage`);
  assert.ok(await page.evaluate("document.querySelector('[data-save-bar]').classList.contains('is-idle')"));
  await page.evaluate(`(() => { const i = document.querySelector('input[name=page_size]');
                               i.value = '300'; i.dispatchEvent(new Event('input', {bubbles: true}));
                               i.dispatchEvent(new Event('change', {bubbles: true})); })()`);
  await page.waitFor("!document.querySelector('[data-save-bar]').classList.contains('is-idle')");
  assert.ok(await page.evaluate("!!document.querySelector('.is-dirty')"));
  noErrors();
});

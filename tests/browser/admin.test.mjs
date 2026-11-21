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
  await page.go(`${BASE}/admin/settings/files`);
  assert.ok(await page.evaluate("document.querySelector('[data-save-bar]').classList.contains('is-idle')"));
  await page.evaluate(`(() => { const i = document.querySelector('input[name=page_size]');
                               i.value = '300'; i.dispatchEvent(new Event('input', {bubbles: true}));
                               i.dispatchEvent(new Event('change', {bubbles: true})); })()`);
  await page.waitFor("!document.querySelector('[data-save-bar]').classList.contains('is-idle')");
  assert.ok(await page.evaluate("!!document.querySelector('.is-dirty')"));
  noErrors();
});

test("auditoría: pulsar una línea abre un modal con sus datos", async () => {
  await page.go(`${BASE}/admin/audit?action=login`);
  const row = "document.querySelector('tr.audit-row')";
  const entry = JSON.parse(await page.evaluate(`${row}.dataset.entry`));
  assert.equal(entry.action, "login");
  await page.evaluate(`${row}.click()`);
  await page.waitFor("document.querySelector('dialog.sw-modal[open] .audit-fields')");
  const text = await page.evaluate("document.querySelector('dialog.sw-modal[open]').textContent");
  assert.match(text, /login/);
  assert.match(text, new RegExp(entry.user));
  assert.ok(await page.evaluate("!!document.querySelector('dialog.sw-modal[open] a[href*=\"action=login\"]')"));
  await page.evaluate("document.querySelector('dialog.sw-modal[open] button[value=ok]').click()");
  await page.waitFor("!document.querySelector('dialog.sw-modal[open]')");
  // Con el teclado: Enter sobre la fila
  await page.evaluate(`${row}.focus()`);
  await page.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await page.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await page.waitFor("document.querySelector('dialog.sw-modal[open] .audit-fields')");
  await page.evaluate("document.querySelector('dialog.sw-modal[open] button[value=ok]').click()");
  noErrors();
});

test("ficha de usuario: la barra de guardar sale al cambiar algo y se va al descartar", async () => {
  await page.go(`${BASE}/admin/users`);
  const href = await page.evaluate("document.querySelector('.user-actions a.btn-icon')?.getAttribute('href')");
  assert.ok(href, "hay un enlace a una ficha");
  await page.go(`${BASE}${href}`);
  const bar = "document.querySelector('[data-user-save]')";
  assert.ok(await page.evaluate(`${bar}.classList.contains('is-idle')`), "sin cambios, sin barra");
  await page.evaluate(`(() => { const s = document.querySelector('select[name=role][form=user-form]');
    s.value = s.value === 'admin' ? 'user' : 'admin'; s.dispatchEvent(new Event('change', {bubbles: true})); })()`);
  await page.waitFor(`!${bar}.classList.contains('is-idle')`);
  await page.evaluate(`${bar}.querySelector('button[type=reset]').click()`);
  await page.waitFor(`${bar}.classList.contains('is-idle')`);
  await page.evaluate(`(() => { const i = document.querySelector('input[name=display_name]');
    i.value = 'Nombre desde el navegador'; i.dispatchEvent(new Event('input', {bubbles: true})); })()`);
  await page.waitFor(`!${bar}.classList.contains('is-idle')`);
  await page.navigating(`${bar}.querySelector('button[type=submit]').click()`);
  assert.equal(await page.evaluate("document.querySelector('input[name=display_name]').value"), "Nombre desde el navegador");
  noErrors();
});

test("vista previa: las extensiones son etiquetas; añadir una avisa y Descartar la quita", async () => {
  // Sin borradores de los tests de antes: con ellos, Descartar pregunta primero (descarta los de todas las páginas)
  await page.go(`${BASE}/admin/settings/preview`);
  await page.evaluate("localStorage.clear()");
  await page.go(`${BASE}/admin/settings/preview`);
  await page.waitFor("document.querySelectorAll('.tags .tag').length > 5");
  const hasZzz = "[...document.querySelectorAll('.tags .tag')].some((t) => t.firstChild.textContent === 'zzz')";
  await page.evaluate(`(() => { const i = document.querySelector('.tags-input'); i.value = 'zzz';
                               i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); })()`);
  await page.waitFor(hasZzz);
  await page.waitFor("!document.querySelector('[data-save-bar]').classList.contains('is-idle')");
  // Descartar (forms.js) vuelve el campo a lo de antes y las etiquetas se repintan (swRenderTags de tag-list.js)
  await page.evaluate("document.querySelector('[data-save-bar] button[type=reset]').click()");
  await page.waitFor(`!(${hasZzz})`);
  await page.waitFor("document.querySelector('[data-save-bar]').classList.contains('is-idle')");
  noErrors();
});

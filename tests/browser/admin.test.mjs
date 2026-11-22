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

test("información: versión, servidor, base de datos, carpetas y componentes, sin errores", async () => {
  await page.go(`${BASE}/admin/settings/system`);
  const text = await page.evaluate("document.body.textContent");
  for (const want of ["Esta instalación", "Hora del servidor", "Esquema", "Carpetas", "Componentes"]) {
    assert.ok(text.includes(want), want);
  }
  noErrors();
});

test("vulnerabilidades: barra de progreso, segundo plano, volver a verla y la tabla ordenable", async () => {
  await page.go(`${BASE}/admin/settings/vulnerabilities`);
  const start = "document.getElementById('advisories-start')";
  await page.evaluate(`${start}.click()`);
  await page.waitFor("document.querySelector('dialog.sw-modal[open] progress.sw-progress')");
  assert.ok(await page.evaluate(`${start}.disabled`), "no se puede pulsar otra vez mientras dura");
  // «Seguir en segundo plano» cierra el modal; la comprobación sigue y «Ver el progreso» la trae al frente
  await page.evaluate("document.querySelector('dialog.sw-modal[open] button[value=ok]').click()");
  await page.waitFor("!document.querySelector('dialog.sw-modal[open]')");
  assert.ok(await page.evaluate("!document.getElementById('advisories-show').hidden"));
  await page.evaluate("document.getElementById('advisories-show').click()");
  await page.waitFor("document.querySelector('dialog.sw-modal[open] progress.sw-progress')");
  // Al acabar, la página se recarga con el resultado
  await page.waitFor("document.querySelector('#advisories details th[data-sort] .sort-btn') && document.readyState === 'complete'", 15000);
  assert.ok(await page.evaluate(`!${start}.disabled`));
  const names = "[...document.querySelectorAll('#advisories details tbody tr')].map((r) => r.cells[0].textContent.trim()).join(',')";
  const header = "document.querySelector('#advisories details th[data-sort] .sort-btn')";
  await page.evaluate(`${header}.click()`);
  assert.equal(await page.evaluate(names), "alfa,zeta");
  await page.evaluate(`${header}.click()`);
  assert.equal(await page.evaluate(names), "zeta,alfa");
  assert.equal(await page.evaluate("document.querySelector('#advisories details th[data-sort]').getAttribute('aria-sort')"),
    "descending");
  noErrors();
});

test("importar de Entra ID: la lista se forma mientras se escribe, sin pulsar Buscar", async () => {
  await page.go(`${BASE}/admin/users/import`);
  await page.evaluate(`(() => { const i = document.querySelector('#import-search input[name=q]');
                               i.value = 'ju'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await page.waitFor("[...document.querySelectorAll('#import-results tbody tr')].some((r) => r.textContent.includes('Juan Pérez'))");
  assert.ok(await page.evaluate("!document.querySelector('#import-results').textContent.includes('Pedro')"));
  assert.match(await page.evaluate("location.search"), /q=ju/);
  // La tabla que llega después también se ordena
  assert.ok(await page.evaluate("!!document.querySelector('#import-results th[data-sort] .sort-btn')"));
  await page.evaluate(`(() => { const i = document.querySelector('#import-search input[name=q]');
                               i.value = 'pe'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await page.waitFor("document.querySelector('#import-results').textContent.includes('Pedro Ruiz')");
  noErrors();
});

test("importar de Entra ID: varias a la vez entre búsquedas, «Mostrar todos» va cargando y avisa de quién no podrá entrar", async () => {
  await page.go(`${BASE}/admin/users/import`);
  const type = (text) => page.evaluate(`(() => { const i = document.querySelector('#import-search input[name=q]');
                                                i.value = ${JSON.stringify(text)}; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  const pick = (name) => page.evaluate(`(() => { const b = [...document.querySelectorAll('input.import-pick')]
                                                  .find((x) => x.dataset.name === ${JSON.stringify(name)});
                                                b.click(); })()`);
  await type("ju");
  await page.waitFor("document.querySelector('input.import-pick')");
  await pick("Juan Pérez");
  await type("pe");
  await page.waitFor("[...document.querySelectorAll('input.import-pick')].some((b) => b.dataset.name === 'Pedro Ruiz')");
  await pick("Pedro Ruiz");
  assert.match(await page.evaluate("document.getElementById('import-count').textContent"), /^2 /);
  // Juan, que no está a la vista, viaja en un campo oculto del formulario
  assert.equal(await page.evaluate("document.querySelectorAll('#import-kept input[name=ids]').length"), 1);
  // Mostrar todos: la primera página y, al bajar, la siguiente; la selección se conserva
  await page.evaluate("document.getElementById('import-all').click()");
  await page.waitFor("document.querySelector('#import-results tbody tr')");
  await page.evaluate("document.getElementById('import-more')?.scrollIntoView()");
  await page.waitFor("document.querySelectorAll('#import-results tbody tr').length === 2");
  assert.equal(await page.evaluate("document.querySelectorAll('input.import-pick:checked').length"), 2);
  // Juan no está asignado a la aplicación (Pedro sí): el aviso
  assert.ok(await page.evaluate("[...document.querySelectorAll('#import-results tbody tr')].find((r) => r.textContent.includes('Juan')).textContent.includes('no podrá entrar')"));
  await page.navigating("document.getElementById('import-selected').click()");
  assert.match(await page.evaluate("document.body.textContent"), /2 personas importadas/);
  noErrors();
});

test("rutas: Examinar abre las carpetas para elegir y al escribir se autocompleta", async () => {
  await page.go(`${BASE}/admin/users?q=ana`);               // la lista filtrada: solo ana
  const href = await page.evaluate("document.querySelector('.user-actions a.btn-icon')?.getAttribute('href')");
  assert.ok(href, "la ficha de ana");
  await page.go(`${BASE}${href}`);
  // Los favoritos están en su pestaña de la ficha
  await page.evaluate("[...document.querySelectorAll('.js-tabs .tabs .tab')].find((b) => b.textContent === 'Favoritos').click()");
  const input = "document.querySelector('#sec-favorites input[name=path]')";
  await page.evaluate(`${input}.parentNode.querySelector('.path-browse').click()`);
  await page.waitFor("[...document.querySelectorAll('dialog.sw-modal[open] .picker-item')].some((b) => b.textContent.trim() === 'Muchos')");
  await page.evaluate("[...document.querySelectorAll('dialog.sw-modal[open] .picker-item')].find((b) => b.textContent.trim() === 'Muchos').click()");
  await page.waitFor("document.querySelector('dialog.sw-modal[open] .picker-where').textContent === '/Muchos'");
  await page.evaluate("document.querySelector('dialog.sw-modal[open] .picker .btn-primary').click()");
  await page.waitFor("!document.querySelector('dialog.sw-modal[open]')");
  assert.equal(await page.evaluate(`${input}.value`), "Muchos");
  // Autocompletado: escribir de verdad (el selector no atiende a los eventos que pone él mismo)
  await page.evaluate(`(() => { const i = ${input}; i.value = ''; i.focus(); })()`);
  await page.send("Input.insertText", { text: "no" });
  await page.waitFor(`[...${input}.list.options].some((o) => o.value === 'notas.md')`);
  noErrors();
});

test("contraseñas: el probador dice regla por regla si se aceptaría", async () => {
  await page.go(`${BASE}/admin/settings/passwords`);
  const form = "document.querySelector('.password-test-form')";
  await page.evaluate(`(() => { const f = ${form}; f.querySelector('[name=test_password]').value = 'qwertyuiop'; f.querySelector('.js-try').click(); })()`);
  await page.waitFor("!document.querySelector('.password-test-result').hidden");
  assert.match(await page.evaluate("document.querySelector('.password-test-summary').textContent"), /Se rechazaría/);
  assert.ok(await page.evaluate("!!document.querySelector('.password-checks li.is-bad')"), "la regla que falla");
  await page.evaluate(`(() => { const f = ${form}; f.querySelector('[name=test_password]').value = 'caballo-grapa-bateria'; f.querySelector('.js-try').click(); })()`);
  await page.waitFor("document.querySelector('.password-test-summary').textContent === 'Se aceptaría.'");
  assert.ok(await page.evaluate("!document.querySelector('.password-checks li.is-bad')"));
  // Ver la contraseña
  await page.evaluate("document.querySelector('.js-show-password').click()");
  assert.equal(await page.evaluate(`${form}.querySelector('[name=test_password]').classList.contains('is-masked')`), false);
  // Nunca un campo de contraseña ni un formulario: el navegador no ofrece guardarla
  assert.equal(await page.evaluate("document.querySelectorAll('#password-test input[type=password], #password-test form').length"), 0);
  // Las reglas de la página, aunque no estén guardadas: marcar «una mayúscula» y probar otra vez
  await page.evaluate("document.querySelector('form.settings-form input[name=password_require][value=upper]').click()");
  await page.evaluate(`${form}.querySelector('.js-try').click()`);
  await page.waitFor("document.querySelector('.password-test-summary').textContent.startsWith('Se rechazaría')");
  assert.match(await page.evaluate("document.querySelector('.password-checks li.is-bad').textContent"), /mayúscula/);
  // Sin la regla del nombre de usuario, el campo del usuario no sale
  await page.evaluate("document.querySelector('form.settings-form input[name=password_reject_username]').click()");
  assert.equal(await page.evaluate("getComputedStyle(document.querySelector('.js-test-username')).display"), "none");
  noErrors();
});

test("roles, vista Paneles: elegir, pestañas, guardar, la estrella y borrar sin recargar la página", async () => {
  // Tres roles, creados como lo haría el formulario de Nuevo rol
  await page.go(`${BASE}/admin/access/roles/list`);
  await page.evaluate(`(async () => {
    const csrf = document.querySelector('input[name=_csrf]').value;
    for (const label of ['Alfa', 'Beta', 'Gamma']) {
      const body = new URLSearchParams({ _csrf: csrf, label, permissions: 'download' });
      await fetch('/admin/access/roles/new', { method: 'POST', body });
    }
  })()`);
  await page.go(`${BASE}/admin/access/roles/panel?r=alfa`);
  await page.evaluate("window.__sinRecargar = true");
  const kept = "window.__sinRecargar === true";
  // Elegir otro en la lista
  await page.evaluate("[...document.querySelectorAll('.md-list .md-item')].find((a) => a.textContent.includes('Gamma')).click()");
  await page.waitFor("document.querySelector('.md-detail .md-title').textContent.trim() === 'Gamma'");
  assert.ok(await page.evaluate(kept), "elegir no recarga");
  assert.match(await page.evaluate("location.search"), /r=gamma/);
  // Pestaña Permisos y guardar
  await page.evaluate("[...document.querySelectorAll('.md-detail .tabs a')].find((a) => a.textContent.startsWith('Permisos')).click()");
  await page.waitFor("!!document.querySelector('#role-tab-form input[value=upload]')");
  await page.evaluate("document.querySelector('#role-tab-form input[value=upload]').click(); document.querySelector('button[form=role-tab-form]').click()");
  await page.waitFor("[...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('Cambios guardados'))");
  assert.ok(await page.evaluate("document.querySelector('#role-tab-form input[value=upload]').checked"));
  assert.ok(await page.evaluate(kept), "guardar no recarga");
  // La estrella: Gamma pasa a ser el de las cuentas nuevas
  await page.evaluate("document.querySelector('.md-detail .role-title button.role-star').click()");
  await page.waitFor("!!document.querySelector('.md-detail .role-title .role-star.is-on')");
  assert.ok(await page.evaluate(kept), "la estrella no recarga");
  // Borrar Beta: el modal propio y fuera de la lista, sin recargar
  await page.evaluate("[...document.querySelectorAll('.md-list .md-item')].find((a) => a.textContent.includes('Beta')).click()");
  await page.waitFor("document.querySelector('.md-detail .md-title').textContent.trim() === 'Beta'");
  await page.evaluate("[...document.querySelectorAll('.md-detail button.btn-danger')].find((b) => b.textContent.includes('Borrar')).click()");
  await page.waitFor("!!document.querySelector('dialog.sw-modal[open]')");
  await page.evaluate("document.querySelector('dialog.sw-modal[open] button[value=ok]').click()");
  await page.waitFor("![...document.querySelectorAll('.md-list .md-item')].some((a) => a.textContent.includes('Beta'))");
  assert.ok(await page.evaluate(kept), "borrar no recarga");
  // Atrás vuelve a la ficha anterior, también sin recargar
  await page.evaluate("history.back()");
  await page.waitFor("location.search.includes('r=beta') || location.search.includes('r=gamma')");
  assert.ok(await page.evaluate(kept));
  noErrors();
});

test("usuarios y grupos, vista Paneles: elegir y cambiar de pestaña sin recargar; lo que usa JavaScript sigue funcionando", async () => {
  await page.go(`${BASE}/admin/users/panel`);
  await page.evaluate("window.__sinRecargar = true");
  const kept = "window.__sinRecargar === true";
  // Elegir a ana: su ficha, con el selector de carpetas («Examinar») y la barra de uso puestos por el JavaScript
  // (por el nombre de usuario exacto: «Juan Pérez», importado antes, también contiene «an»)
  await page.evaluate("[...document.querySelectorAll('.md-list .md-item')].find((a) => a.querySelector('.md-item-text .muted').textContent.trim() === 'ana').click()");
  await page.waitFor("document.querySelector('.md-detail .user-head .inline span').textContent.trim() === 'ana'");
  assert.ok(await page.evaluate(kept), "elegir una persona no recarga");
  assert.ok(await page.evaluate("!!document.querySelector('.md-detail input[name=home_path]').closest('.path-field').querySelector('.path-browse')"),
            "Examinar en el campo de la carpeta personal");
  // Pestaña Grupos y vuelta a Perfil; guardar el perfil
  await page.evaluate("[...document.querySelectorAll('.md-detail .tabs a')].find((a) => a.textContent.startsWith('Grupos')).click()");
  await page.waitFor("location.search.includes('tab=groups')");
  await page.evaluate("[...document.querySelectorAll('.md-detail .tabs a')].find((a) => a.textContent.startsWith('Perfil')).click()");
  await page.waitFor("!!document.querySelector('.md-detail input[name=display_name]')");
  await page.evaluate("document.querySelector('.md-detail input[name=display_name]').value = 'Ana Pruebas'; [...document.querySelectorAll('.md-detail button')].find((b) => b.textContent.includes('Guardar')).click()");
  await page.waitFor("document.querySelector('.md-detail .md-title').textContent.trim() === 'Ana Pruebas'");
  assert.ok(await page.evaluate(kept), "guardar el perfil no recarga");
  assert.ok(await page.evaluate("!!document.querySelector('.md-detail .path-browse')"), "Examinar sigue tras guardar");

  // Grupos: dos, creados como en Nuevo grupo
  await page.evaluate(`(async () => {
    const csrf = document.querySelector('input[name=_csrf]').value;
    for (const name of ['ventas', 'compras']) {
      await fetch('/admin/groups/new', { method: 'POST', body: new URLSearchParams({ _csrf: csrf, name, label: name, source: 'local' }) });
    }
  })()`);
  await page.go(`${BASE}/admin/groups/panel`);
  await page.evaluate("window.__sinRecargar = true");
  await page.evaluate("[...document.querySelectorAll('.md-list .md-item')].find((a) => a.textContent.includes('ventas')).click()");
  await page.waitFor("document.querySelector('.md-detail').textContent.includes('ventas') && location.search.includes('g=')");
  assert.ok(await page.evaluate(kept), "elegir un grupo no recarga");
  noErrors();
});

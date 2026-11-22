// Tests en un navegador de verdad: lo que hace un usuario en el explorador, el visor y el editor. Lo lanza
// tests/integration/test_browser.py contra un servidor real con sus datos (STORAGEWEB_TEST_URL). Cualquier error
// de la consola (JavaScript o la CSP) hace fallar el test.
import assert from "node:assert/strict";
import { after, before, test } from "node:test";

import { findBrowser, launch } from "../../tools/cdp.mjs";

const BASE = process.env.STORAGEWEB_TEST_URL;
const PASSWORD = process.env.STORAGEWEB_TEST_PASSWORD;
let page;

before(async () => {
  page = await launch(process.env.STORAGEWEB_BROWSER || findBrowser());
  await page.login(BASE, "ana", PASSWORD);
});
after(async () => { await page?.close(); });

function noErrors() {
  const found = page.errors.splice(0);
  assert.deepEqual(found, [], "errores en la consola del navegador");
}
const rows = () => page.evaluate("document.querySelectorAll('tr.file-row').length");

test("explorador: seleccionar una fila muestra la barra de selección", async () => {
  await page.go(`${BASE}/f/home/`);
  assert.ok(await page.evaluate("!!document.querySelector('tr.file-row[data-name=\"notas.md\"]')"));
  await page.evaluate("document.querySelector('tr.file-row[data-name=\"texto.txt\"] input.row-check').click()");
  await page.waitFor("!document.getElementById('selection-bar').hidden");
  assert.match(await page.evaluate("document.getElementById('selection-count').textContent"), /1 elemento/);
  noErrors();
});

test("el modal propio pide confirmación antes de borrar", async () => {
  await page.go(`${BASE}/f/home/`);
  const button = "document.querySelector('tr.file-row[data-name=\"borrar.txt\"] form.js-delete button')";
  await page.evaluate(`${button}.click()`);
  await page.waitFor("document.querySelector('dialog.sw-modal[open]')");
  await page.evaluate("document.querySelector('dialog.sw-modal[open] button[value=cancel]').click()");
  await page.waitFor("!document.querySelector('dialog.sw-modal[open]')");
  assert.ok(await page.evaluate("!!document.querySelector('tr.file-row[data-name=\"borrar.txt\"]')"), "cancelar no borra");
  await page.evaluate(`${button}.click()`);
  await page.waitFor("document.querySelector('dialog.sw-modal[open]')");
  await page.navigating("document.querySelector('dialog.sw-modal[open] button[value=ok]').click()");
  assert.ok(await page.evaluate("!document.querySelector('tr.file-row[data-name=\"borrar.txt\"]')"), "aceptar borra");
  noErrors();
});

test("favoritos: la X aparece al pasar el ratón y lo quita sin recargar", async () => {
  await page.go(`${BASE}/f/home/`);
  await page.evaluate(`fetch('/favorites', { method: 'POST', credentials: 'same-origin',
    headers: { 'Accept': 'application/json' },
    body: new URLSearchParams({ _csrf: document.querySelector('input[name=_csrf]').value, root: 'home', path: 'Muchos' }) })`);
  await page.go(`${BASE}/f/home/`);
  const x = "document.querySelector('#fav-list .fav-remove')";
  // Sin ratón (hover: none, como el navegador sin ventana de algunas CI) la X se ve siempre: es para pantallas táctiles
  if (await page.evaluate("matchMedia('(hover: hover)').matches")) {
    assert.equal(await page.evaluate(`getComputedStyle(${x}).opacity`), "0", "sin el ratón encima no se ve");
    const box = await page.evaluate(`(() => { const r = document.querySelector('#fav-list li').getBoundingClientRect();
                                             return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x, y: box.y });
  }
  await page.waitFor(`getComputedStyle(${x}).opacity === "1"`);
  await page.evaluate("window.sinRecargar = true");
  await page.evaluate(`${x}.querySelector('button').click()`);
  await page.waitFor("!document.getElementById('fav-list')");
  assert.equal(await page.evaluate("window.sinRecargar"), true, "sin recargar la página");
  assert.equal(await page.evaluate("document.querySelector('tr.file-row[data-name=\"Muchos\"]').dataset.fav"), "0");
  noErrors();
});

test("carpeta con muchos archivos: carga más al bajar y el filtro busca entre todos", async () => {
  await page.go(`${BASE}/f/home/Muchos/`);
  assert.equal(await rows(), 50);
  await page.evaluate("document.getElementById('load-more').scrollIntoView()");
  await page.waitFor("document.querySelectorAll('tr.file-row').length >= 100");
  await page.evaluate("document.getElementById('load-more').scrollIntoView()");
  await page.waitFor("document.querySelectorAll('tr.file-row').length === 120");
  await page.evaluate(`(() => { const f = document.getElementById('filter-input'); f.value = 'f11';
                               f.dispatchEvent(new Event('input')); })()`);
  await page.waitFor("document.querySelectorAll('tr.file-row').length === 10");
  assert.match(await page.evaluate("document.getElementById('listing-status').textContent"), /coinciden/);
  await page.evaluate(`(() => { const f = document.getElementById('filter-input'); f.value = '';
                               f.dispatchEvent(new Event('input')); })()`);
  // Sin filtro vuelve el principio de la carpeta: 50 filas, o más si con ellas el botón queda cerca de la vista (con
  // filas más bajas, como en Linux, carga otro trozo solo: es lo que tiene que hacer)
  await page.waitFor("document.querySelectorAll('tr.file-row').length >= 50 && " +
                     "!/coinciden/.test(document.getElementById('listing-status').textContent)");
  assert.equal(await page.evaluate("document.querySelector('tr.file-row').dataset.name"), "f000.txt");
  noErrors();
});

test("visor: el diagrama Mermaid se dibuja en su marco aislado", async () => {
  await page.go(`${BASE}/view/home/notas.md`);
  assert.equal(await page.evaluate("document.querySelector('.md strong').textContent"), "negrita");
  await page.waitFor("(() => { const f = document.querySelector('.md-diagram iframe');" +
                     " return f && f.getBoundingClientRect().height > 40; })()", 15000);
  assert.equal(await page.evaluate("document.querySelector('.md-diagram iframe').getAttribute('sandbox')"),
    "allow-scripts");
  noErrors();
});

test("visor: el código sale con colores y sin descuadrar las líneas", async () => {
  await page.go(`${BASE}/view/home/script.py`);
  await page.waitFor("document.getElementById('viewer-text').classList.contains('hljs')");
  const info = await page.evaluate(`(() => {
    const items = [...document.querySelectorAll('#viewer-text > li')];
    return { lines: items.length, text: items.map((li) => li.textContent).join("|"),
             keyword: document.querySelector('#viewer-text .hljs-keyword')?.textContent,
             docLines: items.filter((li) => li.querySelector('.hljs-string')).length,
             color: getComputedStyle(document.querySelector('#viewer-text .hljs-keyword')).color };
  })()`);
  assert.equal(info.lines, 4);
  assert.equal(info.text, 'def saluda(nombre):|    """Varias|    líneas"""|    return f"hola {nombre}"  # fin');
  assert.equal(info.keyword, "def");
  assert.ok(info.docLines >= 3, "la cadena de varias líneas se colorea en cada una");
  assert.notEqual(info.color, await page.evaluate("getComputedStyle(document.body).color"), "tiene su color");
  noErrors();
});

test("visor: una imagen se ve entera y al pulsarla, a su tamaño", async () => {
  await page.go(`${BASE}/view/home/foto.png`);
  await page.waitFor("(() => { const i = document.querySelector('#viewer-image img'); return i && i.complete && i.naturalWidth === 1; })()");
  assert.ok(await page.evaluate("document.getElementById('viewer-media-error').hidden"), "sin aviso de error");
  await page.evaluate("document.getElementById('viewer-image').click()");
  assert.equal(await page.evaluate("document.getElementById('viewer-image').getAttribute('aria-pressed')"), "true");
  noErrors();
});

test("explorador: la miniatura de una imagen sustituye a su icono", async () => {
  await page.go(`${BASE}/f/home/`);
  const cell = "document.querySelector('tr.file-row[data-name=\"foto.png\"] .name-cell')";
  await page.waitFor(`${cell}.classList.contains('has-thumb')`);
  assert.equal(await page.evaluate(`getComputedStyle(${cell}.querySelector('svg.file-icon')).display`), "none");
  // Y en el panel de detalle, al seleccionarla
  await page.evaluate("document.querySelector('tr.file-row[data-name=\"foto.png\"] input.row-check').click()");
  await page.waitFor("!document.getElementById('details-thumb').hidden");
  await page.evaluate("document.querySelector('tr.file-row[data-name=\"foto.png\"] input.row-check').click()");
  noErrors();
});

test("compartir enlace: la ventana lo crea y el enlace abre el archivo", async () => {
  await page.go(`${BASE}/f/home/`);
  await page.evaluate("document.querySelector('tr.file-row[data-name=\"texto.txt\"] input.row-check').click()");
  await page.evaluate("document.querySelector('#selection-bar [data-action=share]').click()");
  await page.waitFor("!!document.querySelector('dialog.sw-modal[open] .share-form')");
  assert.equal(await page.evaluate("document.querySelectorAll('dialog.sw-modal[open] input[type=password]').length"), 0);
  await page.evaluate("[...document.querySelectorAll('dialog.sw-modal[open] .share-form button')].find((b) => b.textContent === 'Crear enlace').click()");
  await page.waitFor("!!document.querySelector('dialog.sw-modal[open] .share-done input')");
  const url = await page.evaluate("document.querySelector('dialog.sw-modal[open] .share-done input').value");
  assert.match(url, /\/s\/[A-Za-z0-9_-]{30,}$/);
  await page.go(url.replace(/^https?:\/\/[^/]+/, BASE));
  assert.match(await page.evaluate("document.body.textContent"), /texto\.txt/);
  noErrors();
});

test("editor: colores debajo del cuadro, al día al escribir, y ocupa toda la ventana", async () => {
  await page.go(`${BASE}/edit/home/script.py`);
  await page.waitFor("document.querySelector('.editor-wrap').classList.contains('is-colored')");
  assert.equal(await page.evaluate("document.querySelector('#editor-colors .hljs-keyword').textContent"), "def");
  assert.equal(await page.evaluate("getComputedStyle(document.getElementById('editor-text')).color"),
    "rgba(0, 0, 0, 0)", "el texto del cuadro es transparente: se ven los colores de debajo");
  await page.evaluate(`(() => { const box = document.getElementById('editor-text');
                               box.value = 'import os\\n' + box.value; box.dispatchEvent(new Event('input')); })()`);
  await page.waitFor("document.getElementById('editor-colors').textContent.startsWith('import os')");
  const same = await page.evaluate(`document.getElementById('editor-colors').textContent.replace(/\\n $/, '')
                                    === document.getElementById('editor-text').value`);
  assert.ok(same, "debajo está el mismo texto que en el cuadro");
  // Números de línea: uno por línea (5 tras añadir «import os»), al lado del texto y sin taparlo
  assert.equal(await page.evaluate("document.getElementById('editor-lines').textContent"), "1\n2\n3\n4\n5");
  const sides = await page.evaluate(`[document.getElementById('editor-gutter').getBoundingClientRect().right,
    document.getElementById('editor-text').getBoundingClientRect().left]`);
  assert.ok(sides[0] <= sides[1] + 1, `los números no tapan el texto (${sides})`);
  await page.evaluate(`(() => { const b = document.getElementById('editor-text'); b.focus();
                               b.setSelectionRange(b.value.length, b.value.length); b.dispatchEvent(new Event('select')); })()`);
  const band = await page.evaluate("parseFloat(document.getElementById('editor-current').style.top)");
  assert.ok(band > 12 + 3 * 20, `la línea del cursor (la 5) está marcada (${band}px)`);
  // Se quitan desde la barra de estado: el texto empieza en el borde
  await page.evaluate("document.getElementById('editor-numbers').click()");
  const off = await page.evaluate(`[getComputedStyle(document.getElementById('editor-gutter')).display,
    document.getElementById('editor-text').getBoundingClientRect().left - document.querySelector('.editor-wrap').getBoundingClientRect().left,
    document.getElementById('editor-numbers').getAttribute('aria-pressed')]`);
  assert.deepEqual(off, ["none", 0, "false"]);
  await page.evaluate("document.getElementById('editor-numbers').click()");
  assert.equal(await page.evaluate("getComputedStyle(document.getElementById('editor-gutter')).display"), "block");
  const status = await page.evaluate(`[document.querySelector('.editor-chip').textContent,
    document.getElementById('editor-indent').textContent, document.getElementById('editor-eol').textContent]`);
  assert.deepEqual(status, ["Python", "Espacios: 4", "LF"], "barra de estado");
  await page.evaluate("document.getElementById('editor-text').setSelectionRange(10, 10)");
  await page.evaluate("document.getElementById('editor-text').dispatchEvent(new Event('select'))");
  assert.match(await page.evaluate("document.getElementById('editor-position').textContent"), /^Línea 2, columna 1/);
  const gap = await page.evaluate("innerHeight - document.querySelector('.editor-box').getBoundingClientRect().bottom");
  assert.ok(gap >= 0 && gap < 80, `el cuadro llega casi al final de la ventana (quedan ${gap}px)`);
  // Se deja como estaba: con cambios sin guardar, salir de la página pediría confirmación
  await page.evaluate(`(() => { const box = document.getElementById('editor-text');
                               box.value = box.value.replace(/^import os\\n/, ''); box.dispatchEvent(new Event('input')); })()`);
  assert.equal(await page.evaluate("document.getElementById('editor-state').hidden"), true);
  noErrors();
});

test("editor: barra de herramientas (Markdown y comentar código) y Tab con varias líneas", async () => {
  const value = () => page.evaluate("document.getElementById('editor-text').value");
  const select = (from, to) => page.evaluate(`document.getElementById('editor-text').setSelectionRange(${from}, ${to})`);
  // Markdown: negrita sobre la selección, y otra vez la quita
  await page.go(`${BASE}/edit/home/notas.md`);
  const md = await value();
  const at = md.indexOf("Texto");
  await select(at, at + 5);
  await page.evaluate("document.querySelector('[data-cmd=bold]').click()");
  assert.ok((await value()).includes("**Texto**"));
  await page.evaluate("document.querySelector('[data-cmd=bold]').click()");
  assert.equal(await value(), md, "pulsar otra vez quita el formato");
  await page.evaluate("document.querySelector('[data-cmd=list]').click()");
  assert.ok((await value()).includes("- Texto"), "lista");
  await page.evaluate("document.querySelector('[data-cmd=list]').click()");
  assert.equal(await value(), md);
  // Código: Ctrl+/ comenta y descomenta las líneas; Tab y Mayús+Tab sangran con espacios (como el archivo)
  await page.go(`${BASE}/edit/home/script.py`);
  const py = await value();
  await select(0, py.length);
  await page.press("/", { ctrl: true, code: "Slash" });
  const commented = await value();
  assert.ok(commented.split("\n").filter((l) => l.trim()).every((l) => l.trimStart().startsWith("# ")), commented);
  await select(0, commented.length);
  await page.press("/", { ctrl: true, code: "Slash" });
  assert.equal(await value(), py);
  await select(0, py.length);
  await page.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  assert.ok((await value()).split("\n").filter((l) => l).every((l) => l.startsWith("    ")), "sangría de 4 espacios");
  await select(0, (await value()).length);
  await page.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: 8 });
  assert.equal(await value(), py);
  assert.equal(await page.evaluate("document.getElementById('editor-state').hidden"), true, "todo como estaba");
  noErrors();
});

test("editor: Ctrl+S guarda y vuelve al visor", async () => {
  await page.go(`${BASE}/view/home/texto.txt`);
  await page.navigating("document.querySelector('a[href=\"/edit/home/texto.txt\"]').click()");
  await page.evaluate(`(() => { const box = document.getElementById('editor-text');
                               box.value = 'primera línea\\nañadida desde el navegador';
                               box.dispatchEvent(new Event('input')); box.focus(); })()`);
  assert.equal(await page.evaluate("document.getElementById('editor-state').hidden"), false, "marca los cambios");
  const loaded = page.next("Page.loadEventFired");
  await page.press("s", { ctrl: true });
  await loaded;
  assert.equal(await page.evaluate("location.pathname"), "/view/home/texto.txt",
    await page.evaluate("(document.querySelector('.flashes, .flash, .toast') || {}).textContent || document.title"));
  assert.match(await page.evaluate("document.getElementById('viewer-text').textContent"), /añadida desde el navegador/);
  noErrors();
});

test("mover: el selector de destino enseña las carpetas y no deja ponerlo donde ya está", async () => {
  await page.go(`${BASE}/f/home/`);
  await page.evaluate("document.querySelector('tr.file-row[data-name=\"texto.txt\"] input.row-check').click()");
  await page.evaluate("document.querySelector('#selection-bar [data-action=move]').click()");
  await page.waitFor("document.getElementById('pick-dest').open");
  const muchos = "[...document.querySelectorAll('#pick-list button')].find((b) => b.textContent.includes('Muchos'))";
  await page.waitFor(`!!${muchos}`);
  assert.equal(await page.evaluate("document.getElementById('pick-ok').disabled"), true, "ya está en esta carpeta");
  await page.evaluate(`${muchos}.click()`);
  await page.waitFor("!document.getElementById('pick-ok').disabled");
  await page.evaluate("document.getElementById('pick-cancel').click()");
  await page.waitFor("!document.getElementById('pick-dest').open");
  noErrors();
});

test("subir: un archivo elegido sube por partes y aparece en la carpeta", async () => {
  await page.go(`${BASE}/f/home/`);
  await page.evaluate(`(() => {
    window.antesDeSubir = true;
    const dt = new DataTransfer();
    dt.items.add(new File(["subido desde el navegador\\n"], "subido.txt", { type: "text/plain" }));
    const input = document.getElementById("file-input");
    input.files = dt.files;
    input.dispatchEvent(new Event("change"));
  })()`);
  // Al acabar recarga la página. Si algo falla, un aviso espera un clic: que el test diga cuál, no que se cuelgue
  try {
    await page.waitFor("!window.antesDeSubir && !!document.querySelector('tr.file-row[data-name=\"subido.txt\"]')", 15000);
  } catch (e) {
    const state = await page.evaluate(`JSON.stringify({
      modal: document.querySelector('dialog.sw-modal[open]')?.textContent.trim() || '',
      panel: document.getElementById('upload-panel')?.hidden, still: !!window.antesDeSubir,
      progress: document.querySelector('#upload-panel .label')?.textContent || '',
      detail: document.querySelector('#upload-panel .detail')?.textContent || '' })`);
    assert.fail(`no se subió: ${state} ${JSON.stringify(page.errors)} ${e.message}`);
  }
  noErrors();
});

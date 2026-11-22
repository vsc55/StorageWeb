// Lo que comparten los tests de navegador (tests/browser/*.test.mjs): abrir el navegador y comprobar que la
// consola no tiene errores. No es un test (no acaba en .test.mjs): no lo lanza tests/integration/test_browser.py.
import assert from "node:assert/strict";

import { findBrowser, launch } from "../../tools/cdp.mjs";

/** Edge o Chrome sin ventana (``STORAGEWEB_BROWSER`` o las rutas de siempre, ver ``findBrowser``). */
export const openBrowser = (options) => launch(findBrowser(), options);

/** Falla si la página tuvo errores en la consola (JavaScript o la CSP) desde la última vez; los vacía. */
export function noErrors(page) {
  const found = page.errors.splice(0);
  assert.deepEqual(found, [], "errores en la consola del navegador");
}

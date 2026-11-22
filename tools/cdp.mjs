// Manejar Edge o Chrome sin ventana por su protocolo de depuración (Chrome DevTools Protocol), con el WebSocket
// de Node 18+. Sin dependencias. Lo usan las capturas de la documentación (tools/screenshots/capture.mjs) y los
// tests de navegador (tests/browser/*.test.mjs).
//
//   const page = await launch(browser, { lang: "es-ES" });
//   await page.go(url); const n = await page.evaluate("document.title"); await page.close();
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Arranca el navegador sin ventana y abre una conexión con su página.
 * @param {string} browser ruta del ejecutable
 * @param {{lang?: string, args?: string[]}} [options]
 */
export async function launch(browser, options = {}) {
  const profile = mkdtempSync(path.join(tmpdir(), "storageweb-cdp-"));
  const args = [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-sync",
    ...(options.scrollbars ? [] : ["--hide-scrollbars"]),     // scrollbars: true, para capturas que las enseñen
    `--lang=${options.lang || "es-ES"}`, "--force-color-profile=srgb",   // y Emulation más abajo (Linux, macOS)
    // Solo habla con el servidor local: sin buscar un proxy (en Windows, la detección automática retrasa la
    // primera página unos 30 segundos)
    "--no-proxy-server",
    // En los contenedores y algunas CI de Linux el sandbox del navegador no puede crear sus espacios de nombres
    ...(process.platform === "linux" && process.env.CI ? ["--no-sandbox"] : []),
    ...(options.args || []), "about:blank",
  ];
  const proc = spawn(browser, args, { stdio: "ignore" });
  let ws;
  const close = async () => {
    try { ws?.close(); } catch { /* ya cerrado */ }
    proc.kill();
    await sleep(500);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* el navegador puede tardar en soltarla */ }
  };
  try {
    // El navegador escribe el puerto elegido en DevToolsActivePort
    let port = "";
    for (let i = 0; i < 200 && !port; i++) {
      const file = path.join(profile, "DevToolsActivePort");
      if (existsSync(file)) port = readFileSync(file, "utf8").split("\n")[0].trim();
      if (!port) await sleep(100);
    }
    if (!port) throw new Error("El navegador no abrió el puerto de depuración");
    const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page");
    ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  } catch (err) {
    await close();
    throw err;
  }

  let seq = 0;
  const pending = new Map();
  const listeners = new Set();
  /** Errores de la página: excepciones de JavaScript y mensajes de error de la consola (p. ej. la CSP). */
  const errors = [];
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(`${msg.error.message} (${msg.error.code})`));
      else resolve(msg.result);
    } else if (msg.method) {
      if (msg.method === "Runtime.exceptionThrown") {
        errors.push(msg.params.exceptionDetails?.exception?.description || msg.params.exceptionDetails?.text);
      } else if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
        errors.push(`${msg.params.entry.source}: ${msg.params.entry.text} ${msg.params.entry.url || ""}`.trim());
      } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
        errors.push(msg.params.args.map((a) => a.value ?? a.description).join(" "));
      }
      for (const fn of [...listeners]) fn(msg);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  /** El siguiente evento ``method`` (p. ej. ``Page.loadEventFired``). */
  const next = (method) => new Promise((resolve) => {
    const fn = (msg) => { if (msg.method === method) { listeners.delete(fn); resolve(msg.params); } };
    listeners.add(fn);
  });
  /** Ejecuta ``expression`` en la página (espera a las promesas) y devuelve su valor. */
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`JavaScript: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result?.value;
  };
  /** Espera a que ``expression`` sea verdadera (o falla tras ``ms``). */
  const waitFor = async (expression, ms = 5000) => {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
      if (await evaluate(`!!(${expression})`)) return;
      await sleep(50);
    }
    throw new Error(`No llegó a cumplirse: ${expression}`);
  };
  // Esperar a «la página nueva» no puede ser esperar al siguiente Page.loadEventFired: si la página de antes aún
  // estaba cargando (p. ej. se recargó sola al acabar una subida y faltaban las miniaturas), ese aviso llega tarde y se
  // toma por el de la nueva, que todavía no ha ejecutado sus scripts (los tests fallaban a veces, sobre todo en la
  // CI). Se marca el documento de antes y se espera a otro, sin la marca, ya cargado del todo.
  const markPrevious = async () => {
    try { await evaluate("window.__swPrevious = true"); } catch { /* sin documento todavía */ }
  };
  const newDocument = async (ms = 15000) => {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
      try {
        if (await evaluate("!window.__swPrevious && document.readyState === 'complete'")) return;
      } catch { /* el documento se está cambiando */ }
      await sleep(50);
    }
    throw new Error("La página nueva no terminó de cargar");
  };
  const go = async (url) => {
    await markPrevious();
    await send("Page.navigate", { url });
    await newDocument();
  };
  /** Ejecuta ``expression`` (que navega: enviar un formulario, un clic) y espera a la página nueva. */
  const navigating = async (expression) => {
    await markPrevious();
    try {
      await evaluate(expression);
    } catch (err) {
      if (!/context|destroyed|navigat/i.test(String(err && err.message))) throw err;   // se fue antes de contestar
    }
    await newDocument();
  };
  /** Inicia sesión con el formulario de usuario y contraseña. */
  const login = async (base, username, password) => {
    await go(`${base}/login?manual=1`);
    await navigating(`(() => {
      document.querySelector("details.login-local")?.setAttribute("open", "");
      const form = document.querySelector("form input[name=username]").form;
      form.username.value = ${JSON.stringify(username)};
      form.password.value = ${JSON.stringify(password)};
      form.submit();
    })()`);
  };
  /** Pulsa una tecla en la página (eventos de teclado de verdad, como el usuario). */
  const press = async (key, { ctrl = false, code = "" } = {}) => {
    const modifiers = ctrl ? (process.platform === "darwin" ? 4 : 2) : 0;
    const base = { key, code: code || `Key${key.toUpperCase()}`, modifiers,
                   windowsVirtualKeyCode: key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0 };
    await send("Input.dispatchKeyEvent", { type: "rawKeyDown", ...base });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  // --lang solo vale en Windows: en Linux el navegador mira LANGUAGE/LANG y en macOS las preferencias del sistema.
  // Así el idioma de las páginas (Accept-Language) y el de navigator/Intl es el pedido en cualquier sistema.
  const lang = options.lang || "es-ES";
  const userAgent = await evaluate("navigator.userAgent");
  await send("Emulation.setUserAgentOverride", { userAgent, acceptLanguage: `${lang},${lang.split("-")[0]}` });
  await send("Emulation.setLocaleOverride", { locale: lang.replace("_", "-") });
  return { send, next, evaluate, waitFor, go, navigating, markPrevious, newDocument, login, press, errors, close };
}

/** El navegador de este equipo: ``STORAGEWEB_BROWSER``, Edge o Chrome en los sitios de siempre, o ``null``. */
export function findBrowser() {
  const which = (name) => {
    for (const dir of (process.env.PATH || "").split(path.delimiter)) {
      const file = path.join(dir, name);
      if (dir && existsSync(file)) return file;
    }
    return "";
  };
  const candidates = [process.env.STORAGEWEB_BROWSER || "",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    which("google-chrome"), which("google-chrome-stable"), which("chromium"), which("chromium-browser"),
    which("microsoft-edge")];
  return candidates.find((p) => p && existsSync(p)) || null;
}

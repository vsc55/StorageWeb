// Capturas de pantalla para la documentación: maneja Edge/Chrome sin ventana por su protocolo de depuración
// (Chrome DevTools Protocol) con el WebSocket de Node 18+. Sin dependencias.
//
//   node capture.mjs <plan.json> <ruta del navegador>
//
// Lo lanza tools/screenshots/demo.py, que prepara la demo y el plan: dirección base, contraseña, carpeta de
// salida y la lista de capturas ({file, path, as, js, scheme, width, height, mobile, wait}).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

/**
 * Se ejecuta en la página (se envía con toString): cambia cada ruta ``from`` por ``to`` en el texto y en los
 * campos, y el resto de esa ruta pasa a barras normales («…\backups» → «…/backups»).
 * @param {[string, string][]} pairs
 */
function disguisePaths(pairs) {
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const fix = (text) => pairs.reduce((t, [from, to]) =>
    t.replace(new RegExp(esc(from) + "([^\\s<>\"']*)", "g"), (_m, rest) => to + rest.replace(/\\/g, "/")), text);
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) n.nodeValue = fix(n.nodeValue);
  document.querySelectorAll("input, textarea").forEach((el) => {
    el.value = fix(el.value);
    el.placeholder = fix(el.placeholder);
  });
}

const [planFile, browser] = process.argv.slice(2);
const plan = JSON.parse(readFileSync(planFile, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(path.join(tmpdir(), "storageweb-shots-"));
const proc = spawn(browser, [
  "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
  "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--hide-scrollbars",
  "--lang=es-ES", "--force-color-profile=srgb", "about:blank",
], { stdio: "ignore" });

let ws;
try {
  // El navegador escribe el puerto elegido en DevToolsActivePort
  let port = "";
  for (let i = 0; i < 150 && !port; i++) {
    const file = path.join(profile, "DevToolsActivePort");
    if (existsSync(file)) port = readFileSync(file, "utf8").split("\n")[0].trim();
    if (!port) await sleep(100);
  }
  if (!port) throw new Error("El navegador no abrió el puerto de depuración");
  const page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page");

  ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let seq = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(`${msg.error.message} (${msg.error.code})`));
      else resolve(msg.result);
    } else if (msg.method) {
      for (const fn of [...listeners]) fn(msg);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const next = (method) => new Promise((resolve) => {
    const fn = (msg) => { if (msg.method === method) { listeners.delete(fn); resolve(msg.params); } };
    listeners.add(fn);
  });
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`JavaScript: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    return r.result?.value;
  };
  const go = async (url) => {
    const loaded = next("Page.loadEventFired");
    await send("Page.navigate", { url });
    await loaded;
  };

  await send("Page.enable");
  await send("Network.enable");
  // Lo que pondría el proxy HTTPS de una instalación real (la demo tiene behind_proxy y la cookie segura;
  // Edge y Chrome admiten cookies seguras en 127.0.0.1). La IP es inventada, de un rango de documentación.
  await send("Network.setExtraHTTPHeaders", { headers: {
    "Accept-Language": "es-ES,es;q=0.9", "X-Forwarded-Proto": "https", "X-Forwarded-For": "192.0.2.15",
  } });

  let current = undefined;  // usuario con la sesión abierta
  for (const shot of plan.shots) {
    const width = shot.width || 1280, height = shot.height || 800, mobile = !!shot.mobile;
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
    await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: shot.scheme || "light" }] });

    if ((shot.as || null) !== (current ?? null)) {
      await send("Network.clearBrowserCookies");
      current = null;
      if (shot.as) {
        await go(`${plan.base}/login?manual=1`);
        const done = next("Page.loadEventFired");
        await evaluate(`(() => {
          document.querySelector("details.login-local")?.setAttribute("open", "");
          const form = document.querySelector("form input[name=username]").form;
          form.username.value = ${JSON.stringify(shot.as)};
          form.password.value = ${JSON.stringify(plan.password)};
          form.submit();
        })()`);
        await done;
        current = shot.as;
      }
    }

    await go(plan.base + shot.path);
    if (shot.js) await evaluate(shot.js);
    await sleep(shot.wait || 400);
    // Las rutas reales de la demo (carpeta temporal de este equipo) se ven como las de un servidor Linux
    await evaluate(`(${disguisePaths.toString()})(${JSON.stringify(plan.replace || [])})`);
    await evaluate("document.activeElement && document.activeElement.blur && !document.querySelector('dialog[open]') && document.activeElement.blur()");
    const { data } = await send("Page.captureScreenshot", { format: "webp", quality: 88 });
    const target = path.join(plan.out, shot.file);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, Buffer.from(data, "base64"));
    console.log(`  ${shot.file}`);
  }
} finally {
  try { ws?.close(); } catch { /* ya cerrado */ }
  proc.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* el navegador puede tardar en soltarla */ }
}

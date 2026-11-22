// Capturas de pantalla para la documentación: maneja Edge/Chrome sin ventana por su protocolo de depuración
// (Chrome DevTools Protocol) con el WebSocket de Node 18+. Sin dependencias.
//
//   node capture.mjs <plan.json> <ruta del navegador>
//
// Lo lanza tools/screenshots/demo.py, que prepara la demo y el plan: dirección base, contraseña, carpeta de
// salida y la lista de capturas ({file, path, as, js, scheme, width, height, mobile, wait}).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { launch, sleep } from "../cdp.mjs";

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

const page = await launch(browser, { lang: "es-ES" });
const { send, evaluate, go } = page;
try {
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
        await page.login(plan.base, shot.as, plan.password);
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
  await page.close();
}

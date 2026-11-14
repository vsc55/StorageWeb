// Cada texto de la extensión tiene su traducción al español (y no sobran traducciones).
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const root = path.join(__dirname, "..");

test("textos de vscode.l10n.t() traducidos al español", () => {
  const dir = path.join(root, "src");
  const src = fs.readdirSync(dir).filter((f) => f.endsWith(".js"))
    .map((f) => fs.readFileSync(path.join(dir, f), "utf8")).join("\n");
  const used = new Set();
  const re = /\bt\(\s*("(?:[^"\\]|\\.)*")/g;
  let m;
  while ((m = re.exec(src))) used.add(JSON.parse(m[1]));
  const es = JSON.parse(fs.readFileSync(path.join(root, "l10n", "bundle.l10n.es.json"), "utf8"));
  assert.deepEqual([...used].filter((s) => !(s in es)), [], "sin traducir");
  assert.deepEqual(Object.keys(es).filter((s) => !used.has(s)), [], "traducciones que ya no se usan");
});

test("textos de package.json (%clave%) en inglés y en español", () => {
  const manifest = fs.readFileSync(path.join(root, "package.json"), "utf8");
  const keys = new Set([...manifest.matchAll(/"%([\w.]+)%"/g)].map((x) => x[1]));
  for (const file of ["package.nls.json", "package.nls.es.json"]) {
    const nls = JSON.parse(fs.readFileSync(path.join(root, file), "utf8"));
    assert.deepEqual([...keys].filter((k) => !(k in nls)), [], file);
    assert.deepEqual(Object.keys(nls).filter((k) => !keys.has(k)), [], file);
  }
});

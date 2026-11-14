// @ts-check
"use strict";
/** Patrones de exclusión sencillos: `**` (cualquier ruta), `*` (dentro de una carpeta), `?` y `[abc]`. */

/** @param {string} pattern */
function globToRegExp(pattern) {
  let out = "";
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "*" && pattern[i + 1] === "*") {
      if (pattern[i + 2] === "/") {
        out += "(?:.*/)?";
        i += 2;
      } else {
        out += ".*";
        i += 1;
      }
    } else if (c === "*") {
      out += "[^/]*";
    } else if (c === "?") {
      out += "[^/]";
    } else if (c === "[" && pattern.indexOf("]", i + 2) > 0) {  // [abc], [a-z], [!abc]
      const end = pattern.indexOf("]", i + 2);
      const body = pattern.slice(i + 1, end).replace(/^!/, "^").replace(/[\\\]]/g, "\\$&");
      out += `[${body}]`;
      i = end;
    } else {
      out += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    }
  }
  return new RegExp(`^${out}$`, process.platform === "win32" ? "i" : "");
}

/**
 * Función que dice si una ruta relativa (POSIX) queda fuera. Una carpeta queda fuera si lo queda
 * ella o cualquier cosa debajo («node_modules/**» excluye la carpeta entera).
 * @param {string[]} patterns @returns {(rel: string, isDir?: boolean) => boolean}
 */
function excluder(patterns) {
  const regexps = patterns.filter(Boolean).map(globToRegExp);
  return (rel, isDir = false) => {
    const candidates = isDir ? [rel, `${rel}/`] : [rel];
    return regexps.some((re) => candidates.some((c) => re.test(c)));
  };
}

/** Carpetas que nunca se sincronizan: control de versiones, dependencias, entornos y cachés que se regeneran. */
const DEFAULT_DIRS = [".git", ".svn", ".hg", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
  ".mypy_cache", ".ruff_cache", ".tox"];

const DEFAULT_EXCLUDES = [
  ...DEFAULT_DIRS.flatMap((d) => [`**/${d}`, `**/${d}/**`]),
  "**/.DS_Store", "**/Thumbs.db", "**/desktop.ini", "**/~$*", "**/*.tmp", "**/*~", "**/.~lock.*#", "**/*.py[co]",
];

/**
 * Las líneas de un `.gitignore` o `.storagewebignore` (en la raíz de la carpeta) → patrones de `excluder`.
 * Lo habitual de gitignore: comentarios (#), `carpeta/` (solo carpetas), `/algo` o `a/b` (desde la raíz),
 * `nombre` (en cualquier sitio), `*`, `**`, `?`. Las negaciones (`!algo`) no se admiten: esas líneas se
 * devuelven aparte para avisar. @param {string} text @returns {{patterns: string[], unsupported: string[]}}
 */
function ignorePatterns(text) {
  const patterns = [], unsupported = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    let line = raw.replace(/(?<!\\)\s+$/, "");
    if (!line.trim() || line.startsWith("#")) continue;
    if (line.startsWith("!")) {
      unsupported.push(line);
      continue;
    }
    line = line.replace(/^\\(?=[#!])/, "");
    const dirOnly = line.endsWith("/");
    line = line.replace(/\/+$/, "");
    const anchored = line.startsWith("/") || line.includes("/");
    line = line.replace(/^\/+/, "");
    if (!line) continue;
    const base = anchored || line.startsWith("**/") ? line : `**/${line}`;
    if (!dirOnly) patterns.push(base);
    patterns.push(`${base}/**`);
  }
  return { patterns, unsupported };
}

module.exports = { DEFAULT_DIRS, DEFAULT_EXCLUDES, excluder, globToRegExp, ignorePatterns };

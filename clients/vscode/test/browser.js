// Un «navegador» mínimo para los tests: inicia sesión en la web de StorageWeb (cookies y CSRF) y acepta
// la página de /connect como haría el usuario. No es un test.
"use strict";

/** @param {string} html */
function csrfOf(html) {
  const m = /name="_csrf" value="([^"]+)"/.exec(html);
  if (!m) throw new Error("no CSRF token in the page");
  return m[1];
}

/** @param {string} base @param {string} username @param {string} password */
async function browserSession(base, username, password) {
  const jar = new Map();
  /** @param {string} path @param {RequestInit} [opts] */
  async function request(path, opts = {}) {
    const headers = { ...(opts.headers || {}), Cookie: [...jar].map(([k, v]) => `${k}=${v}`).join("; ") };
    const resp = await fetch(new URL(path, base), { ...opts, headers, redirect: "manual" });
    const cookies = typeof resp.headers.getSetCookie === "function" ? resp.headers.getSetCookie()
      : [resp.headers.get("set-cookie") || ""];
    for (const c of cookies) {
      const [pair] = c.split(";");
      const i = pair.indexOf("=");
      if (i > 0) jar.set(pair.slice(0, i).trim(), pair.slice(i + 1).trim());
    }
    return resp;
  }
  /** @param {string} path @param {Record<string, string>} fields */
  const post = (path, fields) => request(path, { method: "POST", body: new URLSearchParams(fields),
    headers: { "Content-Type": "application/x-www-form-urlencoded" } });

  const loginPage = await (await request("/login?manual=1")).text();
  const login = await post("/login", { _csrf: csrfOf(loginPage), username, password, next: "" });
  if (login.status !== 302) throw new Error(`login failed: HTTP ${login.status}`);

  return {
    /**
     * Abre la dirección de /connect que da la extensión, acepta (o cancela) y devuelve la vuelta (vscode://…).
     * @param {string} url @param {"allow" | "deny"} [action]
     */
    async authorize(url, action = "allow") {
      const u = new URL(url);
      const page = await (await request(u.pathname + u.search)).text();
      const fields = Object.fromEntries(u.searchParams);
      const done = await post(u.pathname, { ...fields, _csrf: csrfOf(page), action, scope: "write", days: "30" });
      const html = await done.text();
      const m = /id="connect-return" href="([^"]+)"/.exec(html);
      if (!m) throw new Error(`no return link (HTTP ${done.status})`);
      return m[1].replace(/&amp;/g, "&");
    },
  };
}

module.exports = { browserSession };

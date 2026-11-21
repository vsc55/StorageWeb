// Auditoría: pulsar una fila (o Enter con el foco en ella) abre sus datos en un modal. Los datos van en JSON en
// data-entry de la fila y los rótulos, ya traducidos, en <template id="audit-detail"> (admin/audit.html).
(function () {
  "use strict";

  var tpl = document.getElementById("audit-detail");
  if (!tpl || !window.SW) return;
  var t = SW.t;

  // «stage=passkey error=bad_code» → pares, solo si TODO el detalle tiene esa forma (si no, se ve tal cual)
  function pairs(detail) {
    var parts = String(detail || "").trim().split(/\s+/);
    if (!detail || parts.length < 2) return null;
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var m = /^([\w.-]+)=(.*)$/.exec(parts[i]);
      if (!m) return null;
      out.push([m[1], m[2]]);
    }
    return out;
  }

  function copy(text, button) {
    var done = function () { button.textContent = t("Copied"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done);
      return;
    }
    // Sin contexto seguro (http fuera de localhost) no hay portapapeles asíncrono
    var area = document.createElement("textarea");
    area.value = text;
    area.className = "sr-only";
    button.parentNode.appendChild(area);
    area.select();
    try { if (document.execCommand("copy")) done(); } catch (e) { /* no se pudo */ }
    area.remove();
  }

  function show(row) {
    var entry;
    try { entry = JSON.parse(row.dataset.entry); } catch (e) { return; }
    var box = tpl.content.firstElementChild.cloneNode(true);
    box.querySelectorAll("[data-f]").forEach(function (el) {
      var value = entry[el.dataset.f];
      el.textContent = value === "" || value === null || value === undefined ? "—" : String(value);
    });
    box.querySelectorAll("[data-href]").forEach(function (a) {
      var url = entry[a.dataset.href];
      if (url) a.href = url; else a.remove();
    });
    var level = box.querySelector(".level");
    if (level) level.classList.add("level-" + entry.level);
    var found = pairs(entry.detail);
    if (found) {
      var dl = box.querySelector(".audit-pairs");
      found.forEach(function (p) {
        var dt = document.createElement("dt");
        dt.textContent = p[0];
        var dd = document.createElement("dd");
        dd.textContent = p[1];
        dl.appendChild(dt);
        dl.appendChild(dd);
      });
      dl.hidden = false;
    }
    var button = box.querySelector(".audit-copy");
    var plain = { id: entry.id, ts: entry.ts, level: entry.level, user: entry.user, action: entry.action,
                  target: entry.target, ip: entry.ip, detail: entry.detail };
    button.addEventListener("click", function () { copy(JSON.stringify(plain, null, 2), button); });
    SW.show(entry.action + " · " + entry.when, box).then(function () { row.focus(); });
  }

  document.querySelectorAll("tr.audit-row").forEach(function (row) {
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button") || String(window.getSelection() || "")) return;   // seleccionar texto no abre
      show(row);
    });
    row.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(row); }
    });
  });
})();

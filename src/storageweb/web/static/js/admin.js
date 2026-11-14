(function () {
  "use strict";

  // Traducciones: el servidor entrega {texto_fuente: traducción} en <script id="i18n-messages">
  var MESSAGES = {};
  try { MESSAGES = JSON.parse(document.getElementById("i18n-messages").textContent); } catch (e) { MESSAGES = {}; }
  function t(message, params) {
    var text = MESSAGES[message] || message;
    return text.replace(/%\((\w+)\)s/g, function (m, key) {
      return params && params[key] !== undefined ? params[key] : m;
    });
  }

  // Confirmación genérica para formularios destructivos
  document.querySelectorAll("form.js-confirm").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!confirm(f.dataset.confirm || t("Are you sure?"))) e.preventDefault();
    });
  });

  document.documentElement.classList.add("js");

  // Tablas editables (carpetas compartidas, mapeo de roles): añadir y quitar filas
  function addRows(tableId, templateId, buttonId) {
    var table = document.getElementById(tableId);
    var tpl = document.getElementById(templateId);
    var addBtn = document.getElementById(buttonId);
    if (!table || !tpl || !addBtn) return;
    addBtn.addEventListener("click", function () {
      var row = tpl.content.firstElementChild.cloneNode(true);
      table.querySelector("tbody").appendChild(row);
      row.querySelector("input").focus();
      row.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  addRows("mapping-table", "mapping-row-template", "add-mapping");
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".js-remove-row");
    if (!btn) return;
    var form = btn.closest("form");
    btn.closest("tr, li").remove();
    if (form) form.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // Ajustes: la barra de guardado solo aparece con cambios, y avisa al salir sin guardar
  document.querySelectorAll("form[data-watch]").forEach(function (form) {
    var bar = form.querySelector("[data-save-bar]");
    var status = form.querySelector("[data-save-status]");
    var idleText = status ? status.textContent : "";
    var snapshot = function () {
      var out = [];
      form.querySelectorAll("input, select, textarea").forEach(function (el) {
        if (!el.name || el.name === "_csrf") return;
        var checkable = el.type === "checkbox" || el.type === "radio";
        out.push(el.name + "=" + (checkable ? el.checked : el.value));
      });
      return out;
    };
    var initial = snapshot();
    var dirty = false;
    var refresh = function () {
      var now = snapshot();
      var count = 0;
      for (var i = 0; i < Math.max(now.length, initial.length); i++) {
        if (now[i] !== initial[i]) count++;
      }
      dirty = count > 0;
      if (bar) bar.classList.toggle("is-idle", !dirty);
      if (status) status.textContent = dirty ? t("%(count)s unsaved changes", { count: count }) : idleText;
    };
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    form.addEventListener("reset", function () { setTimeout(refresh, 0); });
    form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (e) {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    });
    // Tras un error del servidor la barra sigue visible para volver a guardar
    if (!form.querySelector(".has-error")) refresh();
  });

  // Pestañas a partir de fieldsets: <div class="js-tabs"><fieldset class="tab-panel"><legend>…
  document.querySelectorAll(".js-tabs").forEach(function (box) {
    var panels = Array.prototype.slice.call(box.children).filter(function (el) {
      return el.classList.contains("tab-panel");
    });
    if (panels.length < 2) return;
    var nav = document.createElement("div");
    nav.className = "tabs";
    nav.setAttribute("role", "tablist");
    var show = function (index) {
      panels.forEach(function (p, i) { p.hidden = i !== index; });
      nav.querySelectorAll("button").forEach(function (b, i) {
        b.classList.toggle("active", i === index);
        b.setAttribute("aria-selected", i === index ? "true" : "false");
      });
    };
    panels.forEach(function (panel, i) {
      var legend = panel.querySelector("legend");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "tab";
      b.setAttribute("role", "tab");
      b.textContent = legend ? legend.textContent : String(i + 1);
      b.addEventListener("click", function () { show(i); });
      nav.appendChild(b);
      panel.classList.add("is-tab");
    });
    box.insertBefore(nav, box.firstChild);
    var withError = panels.findIndex(function (p) { return p.querySelector(".has-error, .field-error"); });
    // El buscador lleva a un campo (#f-…): se abre la pestaña que lo contiene
    var byHash = function () {
      var target = location.hash.length > 1 ? document.getElementById(location.hash.slice(1)) : null;
      return target ? panels.findIndex(function (p) { return p.contains(target); }) : -1;
    };
    var start = withError >= 0 ? withError : byHash();
    show(start >= 0 ? start : 0);
    window.addEventListener("hashchange", function () {
      var i = byHash();
      if (i >= 0) {
        show(i);
        document.getElementById(location.hash.slice(1)).scrollIntoView({ block: "center" });
      }
    });
  });

  // Registro en Entra ID: consulta cada pocos segundos si el administrador ya inició sesión
  var regStatus = document.getElementById("register-status");
  var regForm = document.getElementById("register-poll-form");
  if (regStatus && regForm && window.fetch) {
    var csrf = regForm.querySelector("input[name=_csrf]").value;
    var wait = (parseInt(regStatus.dataset.interval, 10) || 5) * 1000;
    var poll = function () {
      fetch(regStatus.dataset.pollUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRF-Token": csrf }
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.status === "pending") {
          if (data.interval) wait = data.interval * 1000;
          regStatus.textContent = data.message || t("Waiting for you to sign in…");
          setTimeout(poll, wait);
        } else if (data.status === "complete") {
          regStatus.textContent = t("Signed in. Registering the application in Entra ID…");
          window.location.href = data.redirect;
        } else {
          regStatus.classList.add("is-error");
          regStatus.textContent = data.message;
        }
      }).catch(function () { setTimeout(poll, wait * 2); });
    };
    setTimeout(poll, wait);
  }

  // Alta de grupo: buscar grupos de Entra ID por nombre y rellenar el Object ID
  var extInput = document.querySelector("input[data-entra-search]");
  if (extInput && window.fetch) {
    var list = document.getElementById(extInput.getAttribute("list"));
    var labelInput = document.querySelector("input[name=label]");
    var timer = null;
    var lastGroups = [];
    var isEntra = function () {
      var checked = document.querySelector("input[name=source]:checked");
      return checked && checked.value === "entra";
    };
    extInput.addEventListener("input", function () {
      clearTimeout(timer);
      var found = lastGroups.find(function (g) { return g.id === extInput.value; });
      if (found) {
        if (labelInput && !labelInput.value) labelInput.value = found.name;
        return;
      }
      if (!isEntra() || extInput.value.length < 2 || /^[0-9a-f-]{36}$/i.test(extInput.value)) return;
      timer = setTimeout(function () {
        fetch(extInput.dataset.entraSearch + "?q=" + encodeURIComponent(extInput.value), {
          headers: { "Accept": "application/json" }, credentials: "same-origin"
        }).then(function (r) { return r.json(); }).then(function (data) {
          lastGroups = data.groups || [];
          list.innerHTML = "";
          lastGroups.forEach(function (g) {
            var opt = document.createElement("option");
            opt.value = g.id;
            opt.label = g.name;
            opt.textContent = g.name;
            list.appendChild(opt);
          });
        }).catch(function () {});
      }, 300);
    });
  }

  // Copiar al portapapeles
  document.querySelectorAll(".js-copy").forEach(function (b) {
    b.addEventListener("click", function () {
      var src = document.querySelector(b.dataset.copy);
      if (!src || !navigator.clipboard) return;
      navigator.clipboard.writeText(src.value).then(function () { b.textContent = t("Copied"); });
    });
  });

  // Matriz de accesos de grupos: color según el nivel y recuento de cambios sin guardar
  var matrix = document.getElementById("access-matrix");
  if (matrix) {
    var status = document.getElementById("matrix-status");
    var bar = matrix.querySelector(".matrix-bar");
    var initialText = status ? status.textContent : "";
    matrix.addEventListener("change", function (e) {
      var sel = e.target;
      if (!sel.classList.contains("access")) return;
      sel.classList.remove("access-none", "access-read", "access-write");
      sel.classList.add("access-" + sel.value);
      sel.classList.toggle("changed", sel.value !== sel.dataset.initial);
      var count = matrix.querySelectorAll("select.access.changed").length;
      if (status) status.textContent = count ? t("%(count)s unsaved changes", { count: count }) : initialText;
      if (bar) bar.classList.toggle("dirty", count > 0);
    });
  }

  // Lista de usuarios: seleccionar todos y recuento para las acciones en bloque
  var bulk = document.getElementById("bulk-form");
  if (bulk) {
    var checks = document.querySelectorAll(".bulk-check");
    var all = document.getElementById("bulk-all");
    var label = document.getElementById("bulk-count");
    var labelText = label ? label.textContent : "";
    var refresh = function () {
      var count = document.querySelectorAll(".bulk-check:checked").length;
      bulk.classList.toggle("has-selection", count > 0);
      if (label) label.textContent = count ? t("%(count)s selected:", { count: count }) : labelText;
      if (all) all.checked = count > 0 && count === checks.length;
    };
    checks.forEach(function (c) { c.addEventListener("change", refresh); });
    if (all) all.addEventListener("change", function () {
      checks.forEach(function (c) { c.checked = all.checked; });
      refresh();
    });
    var action = document.getElementById("bulk-action");
    var group = document.getElementById("bulk-group");
    if (action && group) {
      var syncGroup = function () { group.hidden = action.value !== "add_group"; group.required = !group.hidden; };
      action.addEventListener("change", syncGroup);
      syncGroup();
    }
  }

  // Formulario de usuario nuevo: la contraseña solo aplica a usuarios locales
  var source = document.getElementById("source-select");
  if (source) {
    var pwdField = document.querySelector(".js-local-only");
    var pwdInput = pwdField && pwdField.querySelector("input");
    var sync = function () {
      var isLocal = source.value === "local";
      if (!pwdField) return;
      pwdField.hidden = !isLocal;
      pwdInput.required = isLocal;
      if (!isLocal) pwdInput.value = "";
    };
    source.addEventListener("change", sync);
    sync();
  }
})();

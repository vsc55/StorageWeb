// Formularios de la administración (todas sus páginas): filas editables, barra de guardar con borradores,
// Restablecer y pestañas. Las listas de etiquetas (data-list) van aparte, en admin/tag-list.js.
(function () {
  "use strict";
  var t = window.SW.t;

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

  // Barra de guardar única. Los formularios de configuración (form[data-watch]) la muestran al cambiar
  // algo. Lo que no se guarda queda como borrador (localStorage, por sesión) al cambiar de página: al
  // volver se recupera, y la barra de cualquier página dice qué otras tienen cambios y «Guardar» guarda
  // todas. Si una falla, se abre esa página y se reenvía para que el servidor muestre el error.
  var DRAFTS_KEY = "sw-drafts:" + window.SW.csrf;
  var DRAFT_TTL = 12 * 3600 * 1000;
  var watched = [];         // {form, key, dirty, count, hasError}
  var globalBar = null;     // barra de las páginas sin formulario

  var readDrafts = function () {
    try {
      var all = JSON.parse(localStorage.getItem(DRAFTS_KEY) || "{}");
      var now = Date.now();
      Object.keys(all).forEach(function (k) { if (now - all[k].ts > DRAFT_TTL) delete all[k]; });
      return all;
    } catch (e) { return {}; }
  };
  var writeDrafts = function (all) {
    try {
      if (Object.keys(all).length) localStorage.setItem(DRAFTS_KEY, JSON.stringify(all));
      else localStorage.removeItem(DRAFTS_KEY);
    } catch (e) { /* sin almacenamiento: no hay borradores */ }
  };
  var formKey = function (form) {
    return new URL(form.getAttribute("action") || location.pathname, location.href).pathname;
  };
  var formState = function (form) {
    var out = [];
    form.querySelectorAll("input, select, textarea").forEach(function (el) {
      if (!el.name || el.name === "_csrf" || el.type === "file" || el.disabled) return;
      var checkable = el.type === "checkbox" || el.type === "radio";
      out.push([el.name, checkable ? el.checked : el.value]);
    });
    return out;
  };
  var formEntries = function (form) {
    var out = [];
    new FormData(form).forEach(function (value, name) { if (typeof value === "string") out.push([name, value]); });
    return out;
  };
  var withoutSecrets = function (form, pairs) {
    var secret = {};
    form.querySelectorAll("input[type=password]").forEach(function (el) { if (el.name) secret[el.name] = true; });
    return pairs.filter(function (pair) { return !secret[pair[0]]; });
  };
  var applyState = function (form, state) {
    var wanted = {};
    state.forEach(function (pair) { (wanted[pair[0]] = wanted[pair[0]] || []).push(pair[1]); });
    Object.keys(wanted).forEach(function (name) {
      var find = function () {
        return Array.prototype.slice.call(form.querySelectorAll("[name]")).filter(function (el) {
          return el.name === name && !el.disabled;
        });
      };
      var els = find();
      var adder = form.querySelector("#add-mapping");  // filas del mapeo de roles que falten
      while (els.length < wanted[name].length && adder && name.indexOf("mapping_") === 0) {
        adder.click();
        els = find();
      }
      els.forEach(function (el, i) {
        if (i >= wanted[name].length) return;
        if (el.type === "checkbox" || el.type === "radio") el.checked = Boolean(wanted[name][i]);
        else el.value = wanted[name][i];
        el.dispatchEvent(new Event("swrestore", { bubbles: true }));
      });
    });
  };
  var pageTitle = function () {
    var h = document.querySelector(".settings-head h1, .page-head h1");
    return h ? h.textContent.trim() : document.title;
  };
  var changesText = function (count) {
    return count === 1 ? t("1 unsaved change") : t("%(count)s unsaved changes", { count: count });
  };
  var otherKeys = function () {
    var mine = watched.map(function (w) { return w.key; });
    return Object.keys(readDrafts()).filter(function (k) { return mine.indexOf(k) < 0; });
  };
  var draftCount = function (k) { return readDrafts()[k].count || 1; };
  // Desglose por página: «aquí (1) · Carpetas personales (1)», con enlaces a las otras páginas
  var alsoNode = function (keys, here) {
    var all = readDrafts();
    var span = document.createElement("span");
    span.className = "save-also";
    var parts = [];
    if (here) parts.push(document.createTextNode(t("here") + " (" + here + ")"));
    keys.forEach(function (k) {
      var a = document.createElement("a");
      a.href = k;
      a.textContent = all[k].title;
      var item = document.createElement("span");
      item.appendChild(a);
      item.appendChild(document.createTextNode(" (" + (all[k].count || 1) + ")"));
      parts.push(item);
    });
    parts.forEach(function (node, i) {
      if (i) span.appendChild(document.createTextNode(" · "));
      span.appendChild(node);
    });
    return span;
  };
  // Submenú: punto en las páginas con cambios sin guardar
  var markSubnav = function () {
    var all = readDrafts();
    document.querySelectorAll(".zone-link").forEach(function (a) {
      var path = new URL(a.href, location.href).pathname;
      var pending = Boolean(all[path]) || watched.some(function (w) { return w.dirty && w.key === path; });
      a.classList.toggle("has-draft", pending);
      if (pending) a.title = t("Unsaved changes");
      else a.removeAttribute("title");
    });
  };

  function renderBars() {
    var others = otherKeys();
    var othersTotal = others.reduce(function (sum, k) { return sum + draftCount(k); }, 0);
    markSubnav();
    watched.forEach(function (w) {
      var bar = w.form.querySelector("[data-save-bar]");
      var status = w.form.querySelector("[data-save-status]");
      if (!bar || !status) return;
      var total = (w.dirty ? w.count : 0) + othersTotal;
      status.textContent = total ? changesText(total) + (others.length ? ":" : "") : w.idleText;
      var old = bar.querySelector(".save-also");
      if (old) old.remove();
      if (others.length) status.after(alsoNode(others, w.dirty ? w.count : 0));
      bar.classList.toggle("is-idle", !w.dirty && !w.hasError && !others.length);
      var save = bar.querySelector('button[type="submit"]');
      if (save) save.textContent = others.length ? t("Save all") : t("Save");
    });
    if (watched.length) return;
    // Páginas sin formulario: la misma barra, solo con lo pendiente de otras páginas
    var host = document.querySelector(".zone-layout > .page, .zone-full > .page");
    if (!host) return;
    if (!globalBar) {
      globalBar = document.createElement("div");
      globalBar.className = "save-bar";
      host.appendChild(globalBar);
    }
    globalBar.hidden = others.length === 0;
    globalBar.textContent = "";
    if (!others.length) return;
    var label = document.createElement("span");
    label.textContent = changesText(othersTotal) + ":";
    globalBar.appendChild(label);
    globalBar.appendChild(alsoNode(others, 0));
    var spacer = document.createElement("span");
    spacer.className = "toolbar-spacer";
    globalBar.appendChild(spacer);
    var discard = document.createElement("button");
    discard.type = "button";
    discard.className = "btn btn-ghost";
    discard.textContent = t("Discard");
    discard.addEventListener("click", function () {
      window.SW.confirm(t("Discard the unsaved changes of the other pages?"), { ok: t("Discard"), danger: true })
        .then(function (ok) {
          if (!ok) return;
          writeDrafts({});
          renderBars();
        });
    });
    var save = document.createElement("button");
    save.type = "button";
    save.className = "btn btn-primary";
    save.textContent = t("Save all");
    save.addEventListener("click", function () {
      globalBar.classList.add("is-busy");
      saveDrafts(others, function () { location.reload(); });
    });
    globalBar.appendChild(discard);
    globalBar.appendChild(save);
  }

  // Guarda en el servidor los borradores indicados, uno tras otro; al acabar llama a done()
  function saveDrafts(keys, done) {
    var all = readDrafts();
    var next = function (i) {
      if (i >= keys.length) { done(); return; }
      var k = keys[i];
      var body = new URLSearchParams();
      all[k].entries.forEach(function (pair) { body.append(pair[0], pair[1]); });
      fetch(k, { method: "POST", body: body, credentials: "same-origin", redirect: "manual",
                 headers: { "Content-Type": "application/x-www-form-urlencoded" } })
        .then(function (res) {
          if (res.type === "opaqueredirect" || (res.status >= 300 && res.status < 400)) {
            var current = readDrafts();
            delete current[k];
            writeDrafts(current);
            next(i + 1);
          } else {
            try { sessionStorage.setItem("sw-resubmit", k); } catch (e) { /* nada */ }
            location.href = k;
          }
        })
        .catch(function () { window.SW.alert(t("Network error.")).then(function () { location.reload(); }); });
    };
    next(0);
  }

  // Campos cambiados y sin guardar: se resaltan en el formulario, y las pestañas y los apartados
  // plegados que los contienen llevan un punto (así se encuentran aunque estén ocultos)
  var controlsOf = function (form) {
    return Array.prototype.filter.call(form.querySelectorAll("input, select, textarea"), function (el) {
      return el.name && el.name !== "_csrf" && el.type !== "file" && el.type !== "hidden" && !el.disabled;
    });
  };
  var valueOf = function (el) {
    return el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value;
  };
  var fieldOf = function (el) { return el.closest("label, .entry, td") || el; };
  function markSections(root) {
    (root || document).querySelectorAll(".js-tabs").forEach(function (box) {
      var panels = Array.prototype.filter.call(box.children, function (el) { return el.classList.contains("tab-panel"); });
      var buttons = box.querySelectorAll(".tabs .tab");
      panels.forEach(function (panel, i) {
        if (buttons[i]) buttons[i].classList.toggle("has-dirty", Boolean(panel.querySelector(".is-dirty")));
      });
    });
    (root || document).querySelectorAll("details > summary").forEach(function (summary) {
      summary.classList.toggle("has-dirty", Boolean(summary.parentNode.querySelector(".is-dirty")));
    });
  }
  // Devuelve cuántos campos están cambiados respecto a ``initial`` (Map control → valor al cargar)
  var markDirty = function (form, initial) {
    var fields = new Set();
    controlsOf(form).forEach(function (el) {
      var changed = initial.has(el) ? valueOf(el) !== initial.get(el) : valueOf(el) !== "" && el.type !== "checkbox";
      // En un grupo de opciones solo cuenta (y se resalta) la nueva elegida: la que se desmarca no es otro cambio
      if (changed && el.type === "radio" && !el.checked) changed = false;
      if (changed) fields.add(fieldOf(el));
    });
    form.querySelectorAll(".is-dirty").forEach(function (el) {
      if (!fields.has(el)) { el.classList.remove("is-dirty"); el.removeAttribute("data-dirty-label"); }
    });
    fields.forEach(function (el) {
      el.classList.add("is-dirty");
      el.setAttribute("data-dirty-label", t("unsaved"));
    });
    markSections(form);
    return fields.size;
  };

  // Controles que se pintan solos a partir de su campo (las listas de etiquetas de admin/tag-list.js): tras
  // recuperar un borrador o Descartar, el campo cambió por debajo y hay que repintarlos
  function renderLists(root) {
    (root || document).querySelectorAll("[data-list]").forEach(function (el) { if (el.swRenderTags) el.swRenderTags(); });
  }

  document.querySelectorAll("form[data-watch]").forEach(function (form) {
    var status = form.querySelector("[data-save-status]");
    var w = { form: form, key: formKey(form), dirty: false, count: 0, idleText: status ? status.textContent : "",
              hasError: Boolean(form.querySelector(".has-error")) ||
                Array.prototype.some.call(document.querySelectorAll(".flash-error"), function (el) {
                  return !el.closest(".flashes");  // el aviso del secreto de Entra ID no es un error del formulario
                }) };
    watched.push(w);
    var snapshot = function () { return formState(form).map(function (p) { return p[0] + "=" + p[1]; }); };
    var initial = snapshot();
    var initialValues = new Map();  // valor de cada control al cargar (antes de recuperar un borrador)
    controlsOf(form).forEach(function (el) { initialValues.set(el, valueOf(el)); });
    var submitting = false;
    var refresh = function () {
      var now = snapshot();
      var removed = now.length !== initial.length;  // filas quitadas (mapeo de roles): no tienen campo que marcar
      var count = markDirty(form, initialValues);
      if (!count && removed) count = 1;
      if (!count) {
        for (var i = 0; i < now.length; i++) { if (now[i] !== initial[i]) { count = 1; break; } }
      }
      w.dirty = count > 0;
      w.count = count;
      if (!submitting) {
        var all = readDrafts();
        if (w.dirty) {
          // Las contraseñas y secretos no se guardan en el navegador: al volver hay que escribirlos otra vez
          all[w.key] = { title: pageTitle(), state: withoutSecrets(form, formState(form)),
                         entries: withoutSecrets(form, formEntries(form)), count: count, ts: Date.now() };
        }
        else delete all[w.key];
        writeDrafts(all);
      }
      renderBars();
    };
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    var resetConfirmed = false;
    form.addEventListener("reset", function (e) {
      // «Descartar» descarta todo lo pendiente: esta página y las demás (si hay otras, se confirma una vez)
      var others = otherKeys();
      if (others.length && !resetConfirmed) {
        e.preventDefault();
        var total = (w.dirty ? w.count : 0) + others.reduce(function (sum, k) { return sum + draftCount(k); }, 0);
        window.SW.confirm(t("Discard the %(count)s unsaved changes of every page?", { count: total }),
                          { ok: t("Discard"), danger: true }).then(function (ok) {
          if (!ok) return;
          var all = readDrafts();
          others.forEach(function (k) { delete all[k]; });
          writeDrafts(all);
          resetConfirmed = true;
          form.reset();  // vuelve a lanzar este evento, ya confirmado
          resetConfirmed = false;
        });
        return;
      }
      setTimeout(function () {  // el formulario vuelve a sus valores al terminar el evento
        // Los Restablecer pendientes también se deshacen: vuelven su etiqueta («modificado») y su botón
        form.querySelectorAll("[data-sw-reset-pending]").forEach(function (b) {
          b.hidden = false;
          b.removeAttribute("data-sw-reset-pending");
          var badge = b.previousElementSibling;
          if (badge && badge.hasAttribute("data-sw-text")) {
            badge.textContent = badge.getAttribute("data-sw-text");
            badge.classList.remove("origin-pending");
          }
        });
        renderLists(form);
        refresh();
      }, 0);
    });
    form.addEventListener("submit", function (e) {
      var others = otherKeys();
      if (others.length && !submitting) {
        // Primero las otras páginas; luego esta, de forma normal (el servidor muestra el resultado)
        e.preventDefault();
        submitting = true;
        var bar = form.querySelector("[data-save-bar]");
        if (bar) bar.classList.add("is-busy");
        saveDrafts(others, function () { form.submit(); });
      }
      submitting = true;
      var all = readDrafts();
      delete all[w.key];
      writeDrafts(all);
    });
    var draft = readDrafts()[w.key];
    if (draft && !w.hasError) { applyState(form, draft.state); renderLists(form); }
    refresh();
    try {
      if (sessionStorage.getItem("sw-resubmit") === w.key) {
        sessionStorage.removeItem("sw-resubmit");
        if (draft) { submitting = true; form.submit(); }
      }
    } catch (e) { /* nada */ }
  });
  renderBars();

  // Restablecer un campo: pone su valor predeterminado en el formulario (se aplica al guardar). Si no
  // encuentra los controles (logo) o es un secreto, el botón envía el formulario de restablecer del servidor.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".js-reset-field");
    if (!btn) return;
    var path = btn.value;
    var controls = Array.prototype.slice.call(document.querySelectorAll("[data-field]")).filter(function (el) {
      return el.getAttribute("data-field") === path && !el.closest("template");
    });
    if (!controls.length || controls.some(function (el) { return el.type === "password"; })) return;
    e.preventDefault();
    var value = JSON.parse(btn.getAttribute("data-default"));
    var form = controls[0].form || controls[0].closest("form");
    // Un control puede pedir confirmación antes (una lista de etiquetas, admin/tag-list.js: qué se añade y qué se
    // quita); su swConfirmReset devuelve una promesa
    if (controls.length === 1 && typeof controls[0].swConfirmReset === "function") {
      controls[0].swConfirmReset(value).then(function (ok) { if (ok) resetTo(btn, controls, form, value); });
      return;
    }
    resetTo(btn, controls, form, value);
  });

  function resetTo(btn, controls, form, value) {
    if (value !== null && typeof value === "object") {
      // Listas de filas (mapeo de roles): se quitan todas y queda una vacía
      var rows = controls.map(function (el) { return el.closest("tr"); }).filter(Boolean);
      var tbody = rows.length ? rows[0].parentNode : null;
      rows.forEach(function (row) { if (row.parentNode) row.parentNode.removeChild(row); });
      var tpl = form && form.querySelector("template");
      if (tbody && tpl) tbody.appendChild(tpl.content.firstElementChild.cloneNode(true));
    } else {
      controls.forEach(function (el) {
        if (el.type === "checkbox") el.checked = Boolean(value);
        else if (el.type === "color") { if (value) el.value = value; }
        else el.value = value === null ? "" : String(value);
        if (el.swRenderTags) el.swRenderTags();   // una lista de etiquetas: se vuelve a pintar
      });
    }
    var badge = btn.previousElementSibling;
    if (badge && badge.classList.contains("origin")) {
      if (!badge.hasAttribute("data-sw-text")) badge.setAttribute("data-sw-text", badge.textContent);  // para Descartar
      badge.textContent = t("default (save to apply)");
      badge.classList.add("origin-pending");
    }
    btn.hidden = true;
    btn.setAttribute("data-sw-reset-pending", "");
    if (form) form.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // Pestañas a partir de fieldsets: <div class="js-tabs"><fieldset class="tab-panel"><legend>…
  document.querySelectorAll(".js-tabs").forEach(function (box) {
    var panels = Array.prototype.slice.call(box.children).filter(function (el) {
      return el.classList.contains("tab-panel");
    });
    if (panels.length < 2) return;
    var nav = document.createElement("div");
    nav.className = "tabs";
    nav.setAttribute("role", "tablist");
    // La pestaña abierta se recuerda (por página y grupo de pestañas) para que F5 vuelva a ella
    var boxes = document.querySelectorAll(".js-tabs");
    var memoryKey = "sw-tab:" + location.pathname + ":" + Array.prototype.indexOf.call(boxes, box);
    var remembered = function () {
      try { return parseInt(window.sessionStorage.getItem(memoryKey), 10); } catch (e) { return NaN; }
    };
    var show = function (index) {
      panels.forEach(function (p, i) { p.hidden = i !== index; });
      nav.querySelectorAll("button.tab").forEach(function (b, i) {
        b.classList.toggle("active", i === index);
        b.setAttribute("aria-selected", i === index ? "true" : "false");
      });
      try { window.sessionStorage.setItem(memoryKey, String(index)); } catch (e) { /* sin almacenamiento: no pasa nada */ }
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
    box.classList.add("tabs-side");      // en columna a la izquierda (admin.css); sin JS, los fieldsets uno tras otro
    var withError = panels.findIndex(function (p) { return p.querySelector(".has-error, .field-error"); });
    // El buscador lleva a un campo (#f-…): se abre la pestaña que lo contiene
    var byHash = function () {
      var target = location.hash.length > 1 ? document.getElementById(location.hash.slice(1)) : null;
      return target ? panels.findIndex(function (p) { return p.contains(target); }) : -1;
    };
    // Primero la que tiene un error; luego la del campo al que lleva el buscador; luego la que estaba abierta
    var start = withError >= 0 ? withError : byHash();
    if (start < 0) {
      var kept = remembered();
      start = kept >= 0 && kept < panels.length ? kept : 0;
    }
    show(start);
    window.addEventListener("hashchange", function () {
      var i = byHash();
      if (i >= 0) {
        show(i);
        document.getElementById(location.hash.slice(1)).scrollIntoView({ block: "center" });
      }
    });
    markSections(box);
  });
})();

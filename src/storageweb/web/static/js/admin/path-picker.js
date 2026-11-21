// Campos de ruta de la administración: un botón «Examinar» al lado (una ventana para ir por las carpetas y elegir)
// y autocompletado mientras se escribe (lo que hay en la carpeta que llevas escrita). Lo que lista lo da el servidor
// (/admin/browse, admin.browse → core/pathpicker). Cada campo dice a dónde mira:
//
//   <input data-browse="/admin/browse?scope=root&user=…"  data-root-from="select[name=root]" data-files="1">  favoritos
//   <input data-browse="/admin/browse?scope=location" data-location-from="select[name=location]" data-start="/srv">
//   <input data-browse="/admin/browse?scope=location" data-location="nas">        (una ubicación fija)
//
// Sin ubicación (vacía), el disco del servidor: rutas absolutas y solo carpetas. Al elegir, el campo cambia como si
// se hubiera escrito (eventos input y change: la barra de guardar lo ve).
(function () {
  "use strict";

  var fields = document.querySelectorAll("input[data-browse]");
  if (!fields.length) return;
  var t = window.SW.t;
  var counter = 0;
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute("content") : "";

  function scopeOf(input) {
    // Dónde mira ahora: depende del desplegable de al lado, si lo hay
    var form = input.form || document;
    var params = new URLSearchParams();
    var location = input.dataset.location || "";
    if (input.dataset.locationFrom) {
      var select = form.querySelector(input.dataset.locationFrom) || document.querySelector(input.dataset.locationFrom);
      location = select ? select.value : "";
    }
    if (location) params.set("location", location);
    if (input.dataset.rootFrom) {
      var rootSelect = form.querySelector(input.dataset.rootFrom) || document.querySelector(input.dataset.rootFrom);
      if (rootSelect) params.set("root", rootSelect.value);
    }
    if (input.dataset.start) params.set("start", input.dataset.start);
    if (input.dataset.files) params.set("files", "1");
    var disk = input.dataset.browse.indexOf("scope=location") !== -1 && !location;
    return { params: params, disk: disk };
  }

  function fetchListing(input, path, noStart) {
    var scope = scopeOf(input);
    scope.params.set("path", path);
    if (noStart) scope.params.delete("start");     // el principio (las carpetas permitidas), no el punto de partida
    var url = input.dataset.browse + (input.dataset.browse.indexOf("?") === -1 ? "?" : "&") + scope.params.toString();
    // El token CSRF en la cabecera: el servidor solo contesta al JavaScript de la propia página
    return fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json", "X-CSRF-Token": csrf } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function setValue(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // ------------------------------------------------------------------ Examinar
  function openPicker(input) {
    var disk = scopeOf(input).disk;
    var files = !!input.dataset.files;
    var panel = document.createElement("div");
    panel.className = "picker";
    var where = document.createElement("p");
    where.className = "picker-where mono small";
    var note = document.createElement("p");
    note.className = "muted small";
    note.hidden = true;
    var list = document.createElement("ul");
    list.className = "picker-list";
    var choose = document.createElement("button");
    choose.type = "button";
    choose.className = "btn btn-primary";
    choose.textContent = t("Choose this folder");
    panel.appendChild(where);
    panel.appendChild(list);
    panel.appendChild(note);
    panel.appendChild(choose);
    var current = "";

    function close() { var d = panel.closest("dialog"); if (d) d.close(); }

    function row(label, icon, onClick, extraClass) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "picker-item" + (extraClass ? " " + extraClass : "");
      b.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#i-' + icon + '"></use></svg>';
      var span = document.createElement("span");
      span.textContent = label;
      b.appendChild(span);
      b.addEventListener("click", onClick);
      li.appendChild(b);
      list.appendChild(li);
    }

    function go(path, noStart) {
      list.innerHTML = "";
      note.hidden = true;
      where.textContent = t("Loading…");
      fetchListing(input, path, noStart).then(function (data) {
        current = data.path || "";
        // En el disco con varias carpetas permitidas, el principio es la lista de ellas: ahí no se elige nada
        choose.disabled = !!data.top;
        where.textContent = data.top ? t("Allowed server folders") : disk ? (current || "/") : "/" + current;
        if (data.parent !== null && data.parent !== undefined) {
          row(t("Up"), "chevron-left", function () { go(data.parent, data.parent === ""); }, "picker-up");
        }
        data.entries.forEach(function (e) {
          if (e.is_dir) row(e.name, "folder", function () { go(e.path); });
          else if (files) row(e.name, "file", function () { setValue(input, e.path); close(); });
        });
        if (!data.entries.length) {
          note.textContent = data.error || t("Empty folder.");
          note.hidden = false;
        } else if (data.error || data.truncated) {
          note.textContent = data.error || t("Only the first ones are shown: write more of the path.");
          note.hidden = false;
        }
      }).catch(function () { where.textContent = t("Network error."); });
    }

    choose.addEventListener("click", function () { setValue(input, current); close(); });
    window.SW.show(input.dataset.pickTitle || t("Choose a folder"), panel, { ok: t("Cancel") }).then(function () {
      input.focus();
    });
    // Empieza donde apunta el campo (o en su carpeta), si hay algo escrito
    var value = input.value.trim();
    go(disk ? value : value.replace(/^\/+|\/+$/g, ""));
  }

  // ------------------------------------------------------------------ autocompletado
  function wireSuggest(input) {
    var list = document.createElement("datalist");
    list.id = "path-suggest-" + (++counter);
    document.body.appendChild(list);
    input.setAttribute("list", list.id);
    input.setAttribute("autocomplete", "off");
    var timer = null;
    var seq = 0;
    input.addEventListener("input", function (event) {
      if (!event.isTrusted) return;          // lo que pone el propio selector no pide sugerencias
      clearTimeout(timer);
      timer = setTimeout(function () {
        var value = input.value;
        var disk = scopeOf(input).disk;
        var cut = Math.max(value.lastIndexOf("/"), disk ? value.lastIndexOf("\\") : -1);
        var folder = cut >= 0 ? value.slice(0, cut + 1) : "";
        var prefix = (cut >= 0 ? value.slice(cut + 1) : value).toLowerCase();
        if (disk && !folder) { list.innerHTML = ""; return; }      // en el disco, desde una ruta absoluta
        var mine = ++seq;
        fetchListing(input, disk ? folder : folder.replace(/\/+$/, "")).then(function (data) {
          if (mine !== seq) return;
          list.innerHTML = "";
          data.entries.filter(function (e) { return e.name.toLowerCase().indexOf(prefix) === 0; }).slice(0, 50)
            .forEach(function (e) {
              var option = document.createElement("option");
              option.value = e.path + (e.is_dir && !disk ? "/" : "");
              list.appendChild(option);
            });
        }).catch(function () { /* sin sugerencias: se sigue escribiendo */ });
      }, 250);
    });
  }

  Array.prototype.forEach.call(fields, function (input) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn path-browse";
    button.innerHTML = '<svg class="icon icon-sm" aria-hidden="true"><use href="#i-folder"></use></svg>';
    var label = document.createElement("span");
    label.textContent = t("Browse");
    button.appendChild(label);
    button.disabled = input.disabled || input.readOnly;
    button.addEventListener("click", function () { openPicker(input); });
    var wrap = document.createElement("span");
    wrap.className = "path-field";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    wrap.appendChild(button);
    wireSuggest(input);
  });
})();

(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var input = document.getElementById("file-input");
  var folderInput = document.getElementById("folder-input");
  var dropzone = document.getElementById("dropzone");
  var panel = document.getElementById("upload-panel");
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  var t = window.SW.t;

  var MAX_RETRIES = 8;
  var current = { xhr: null, id: null, cancelled: false };

  // ------------------------------------------------------------------ utilidades

  function fmt(bytes) {
    var units = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return (i ? bytes.toFixed(1) : bytes) + " " + units[i];
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // localStorage puede no estar disponible (modo privado, políticas…)
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (e) { return null; }
  }

  // Petición con XHR (permite progreso de subida y cancelar)
  function request(method, url, body, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      current.xhr = xhr;
      xhr.open(method, url);
      xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.setRequestHeader("Accept", "application/json");
      if (body && !(body instanceof Blob)) {
        xhr.setRequestHeader("Content-Type", "application/json");
        body = JSON.stringify(body);
      } else if (body) {
        xhr.setRequestHeader("Content-Type", "application/octet-stream");
      }
      if (onProgress) xhr.upload.onprogress = function (e) { onProgress(e.loaded); };
      xhr.onload = function () {
        var data = null;
        try { data = xhr.responseText ? JSON.parse(xhr.responseText) : {}; } catch (e) { data = {}; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject({ status: xhr.status, data: data });
      };
      xhr.onerror = function () { reject({ status: 0, data: {} }); };
      xhr.onabort = function () { reject({ status: -1, data: {} }); };
      xhr.send(body || null);
    });
  }

  function errorText(err) {
    if (err.data && err.data.error) return err.data.error;
    if (err.status === 413) return t("The part or the file is too large for the server.");
    if (err.status === 0) return t("Network error.");
    return t("HTTP error %(status)s.", {status: err.status});
  }

  // ------------------------------------------------------------------ subida por partes

  function uploadFile(item, ui) {
    var api = form.dataset.api;
    var file = item.file;
    // Clave para reanudar la misma subida tras recargar la página (con su subcarpeta, si viene de una carpeta)
    var key = "sw-upload:" + [form.dataset.root, form.dataset.path, item.folder, file.name, file.size,
                              file.lastModified].join("|");
    var id = store(key), received = 0, chunk = 0;

    function start() {
      if (!id) return Promise.resolve(null);
      return request("GET", api + "/" + id).then(function (st) {
        if (st.size !== file.size) return null;
        received = st.received; chunk = st.chunk_size; return st;
      }, function () { return null; });
    }

    return start().then(function (st) {
      if (st) return;
      return request("POST", api, { root: form.dataset.root, path: form.dataset.path, folders: item.folder,
                                    name: file.name, size: file.size })
        .then(function (r) { id = r.id; chunk = r.chunk_size; received = 0; store(key, id); });
    }).then(function () {
      current.id = id;
      var retries = 0;

      function next() {
        if (current.cancelled) return Promise.reject({ status: -1, data: {} });
        if (received >= file.size) return Promise.resolve();
        var blob = file.slice(received, Math.min(received + chunk, file.size));
        return request("PUT", api + "/" + id + "?offset=" + received, blob, function (loaded) {
          ui(received + loaded);
        }).then(function (r) {
          received = r.received; retries = 0; ui(received); return next();
        }, function (err) {
          if (err.status === -1) throw err;                          // cancelado
          if (err.status === 409 && typeof err.data.received === "number") {
            received = err.data.received; return next();             // el servidor dice dónde seguir
          }
          var transient = err.status === 0 || err.status >= 500 && err.status !== 507;
          if (!transient || ++retries > MAX_RETRIES) throw err;
          // Reintento con espera creciente; se consulta el offset real antes de seguir
          return sleep(Math.min(30000, 1000 * Math.pow(2, retries))).then(function () {
            return request("GET", api + "/" + id).then(function (st) { received = st.received; }, function () {});
          }).then(next);
        });
      }
      return next();
    }).then(function () {
      return request("POST", api + "/" + id + "/complete");
    }).then(function (r) {
      store(key, null);
      return r;
    }, function (err) {
      if (err.status === 404) store(key, null);  // la subida ya no existe en el servidor
      throw err;
    });
  }

  // Archivos sueltos (File) o de una carpeta ({file, folder}); con el selector de carpetas, la subcarpeta sale
  // de webkitRelativePath («Viaje/Fotos/a.jpg» → «Viaje/Fotos»)
  function asItem(f) {
    if (f.file) return f;
    var rel = f.webkitRelativePath || "";
    return { file: f, folder: rel.indexOf("/") >= 0 ? rel.slice(0, rel.lastIndexOf("/")) : "" };
  }

  function pathOf(item) { return item.folder ? item.folder + "/" + item.file.name : item.file.name; }

  function uploadAll(files) {
    if (!files || !files.length || !form) return;
    var maxFile = parseInt(form.dataset.maxFile, 10) || 0;
    var list = Array.prototype.map.call(files, asItem);
    var tooBig = list.filter(function (it) { return maxFile && it.file.size > maxFile; });
    if (tooBig.length) {
      list = list.filter(function (it) { return tooBig.indexOf(it) < 0; });
      window.SW.alert(t("These files exceed the maximum size allowed (%(max)s):", {max: fmt(maxFile)}) + "\n" +
                      tooBig.map(pathOf).join("\n"))
        .then(function () { if (list.length) startUpload(list); });
      return;
    }
    startUpload(list);
  }

  // Lo que se arrastra: con carpetas, se recorren (y sus subcarpetas) y cada archivo lleva la suya
  function droppedItems(dt) {
    var entries = Array.prototype.map.call(dt.items || [], function (i) {
      return i.kind === "file" && i.webkitGetAsEntry ? i.webkitGetAsEntry() : null;   // hay que pedirlo ya
    }).filter(Boolean);
    if (!entries.some(function (e) { return e.isDirectory; })) return Promise.resolve(dt.files);
    var out = [];
    var walk = function (entry, folder) {
      if (entry.isFile) {
        return new Promise(function (resolve) {
          entry.file(function (f) { out.push({ file: f, folder: folder }); resolve(); }, function () { resolve(); });
        });
      }
      var reader = entry.createReader();
      var sub = folder ? folder + "/" + entry.name : entry.name;
      var batch = function () {   // readEntries devuelve las entradas por tandas, hasta una vacía
        return new Promise(function (resolve) { reader.readEntries(resolve, function () { resolve([]); }); })
          .then(function (list) {
            if (!list.length) return null;
            return list.reduce(function (p, e) { return p.then(function () { return walk(e, sub); }); },
                               Promise.resolve()).then(batch);
          });
      };
      return batch();
    };
    return entries.reduce(function (p, e) { return p.then(function () { return walk(e, ""); }); }, Promise.resolve())
      .then(function () { return out; });
  }

  function startUpload(list) {

    var total = list.reduce(function (s, it) { return s + it.file.size; }, 0) || 1;
    var done = 0, errors = [], bar = panel.querySelector(".bar"),
        label = panel.querySelector(".label"), detail = panel.querySelector(".detail");
    current.cancelled = false;
    panel.hidden = false;
    if (input) input.disabled = true;
    if (folderInput) folderInput.disabled = true;
    window.onbeforeunload = function () { return t("An upload is in progress"); };

    var chain = Promise.resolve();
    list.forEach(function (item, i) {
      var file = item.file;
      chain = chain.then(function () {
        if (current.cancelled) return;
        detail.textContent = t("File %(index)s of %(total)s: %(name)s", {index: i + 1, total: list.length, name: pathOf(item)});
        return uploadFile(item, function (bytes) {
          var pct = Math.min(100, Math.floor(((done + bytes) / total) * 100));
          bar.style.width = pct + "%";
          label.textContent = pct + "% · " + fmt(done + bytes) + " / " + fmt(total);
        }).then(function () { done += file.size; }, function (err) {
          if (err.status === -1) return;
          errors.push(pathOf(item) + ": " + errorText(err));
          done += file.size;
        });
      });
    });

    chain.then(function () {
      window.onbeforeunload = null;
      if (!errors.length) { window.location.reload(); return; }
      window.SW.alert(t("Could not upload:") + "\n" + errors.join("\n")).then(function () { window.location.reload(); });
    });
  }

  if (panel) {
    document.getElementById("upload-cancel").addEventListener("click", function () {
      window.SW.confirm(t("Cancel the upload?"), { danger: true }).then(function (ok) {
        if (ok) cancelUpload();
      });
    });
  }

  function cancelUpload() {
    current.cancelled = true;
    if (current.xhr) current.xhr.abort();
    if (current.id) {
      var xhr = new XMLHttpRequest();
      xhr.open("DELETE", form.dataset.api + "/" + current.id);
      xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.send();
    }
  }

  if (input) {
    input.addEventListener("change", function () { uploadAll(input.files); });
  }
  if (folderInput) {
    folderInput.addEventListener("change", function () { uploadAll(folderInput.files); });
  }

  // Solo archivos que vienen de fuera (del equipo); arrastrar filas para mover no es subir
  function bringsFiles(e) {
    return !!(e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") !== -1);
  }

  if (dropzone) {
    ["dragenter", "dragover"].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
        if (!bringsFiles(e)) return;
        e.preventDefault();
        dropzone.classList.add("over");
      });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
        e.preventDefault();
        if (ev === "drop" || e.target === dropzone) dropzone.classList.remove("over");
      });
    });
    document.addEventListener("drop", function (e) {
      if (!bringsFiles(e) || !e.dataTransfer.files.length) return;
      droppedItems(e.dataTransfer).then(uploadAll);
    });
  }

  // ------------------------------------------------------------------ acciones de la tabla

  function wireRename(f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.renamed === "1") { delete f.dataset.renamed; return; }
      e.preventDefault();
      window.SW.prompt(t("New name:"), f.dataset.name).then(function (name) {
        name = (name || "").trim();
        if (!name || name === f.dataset.name) return;
        f.querySelector('input[name="name"]').value = name;
        f.dataset.renamed = "1";
        f.submit();
      });
    });
  }
  document.querySelectorAll("form.js-rename").forEach(wireRename);

  // ------------------------------------------------------------------ favoritos: la X de la lista
  // Quita el favorito sin recargar; si es la carpeta en la que estás, el formulario sigue (y la estrella se apaga)
  document.querySelectorAll("form.fav-remove").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.hasAttribute("data-here")) return;
      e.preventDefault();
      // getAttribute: el formulario tiene un campo «action», que tapa la propiedad f.action
      fetch(f.getAttribute("action"), { method: "POST", body: new FormData(f), credentials: "same-origin",
                        headers: { "Accept": "application/json" } })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          var li = f.closest("li");
          var list = li.parentNode;
          li.remove();
          // La fila del explorador, si está a la vista, deja de ser favorita (panel de detalle)
          var table = document.getElementById("file-table");
          if (table && table.dataset.root === f.elements.root.value) {
            table.querySelectorAll("tr.file-row").forEach(function (row) {
              if (row.dataset.rel === f.elements.path.value) row.dataset.fav = "0";
            });
          }
          if (!list.children.length) {   // sin favoritos: fuera la sección
            var title = list.previousElementSibling;
            if (title && title.classList.contains("panel-title")) title.remove();
            list.remove();
          }
        })
        .catch(function () { window.SW.alert(t("Network error.")); });
    });
  });

  // ------------------------------------------------------------------ explorador: selección y detalle

  var table = document.getElementById("file-table");
  if (!table) return;

  var rows = Array.prototype.slice.call(table.querySelectorAll("tr.file-row"));
  var selectAll = document.getElementById("select-all");
  var bar = document.getElementById("selection-bar");
  var barCount = document.getElementById("selection-count");
  var details = {
    empty: document.getElementById("details-empty"),
    multi: document.getElementById("details-multi"),
    multiCount: document.getElementById("details-multi-count"),
    body: document.getElementById("details-body"),
    icon: document.getElementById("details-icon"),
    name: document.getElementById("details-name"),
    kind: document.getElementById("details-kind"),
    size: document.getElementById("details-size"),
    mtime: document.getElementById("details-mtime"),
    open: document.getElementById("details-open"),
    download: document.getElementById("details-download"),
    fav: document.getElementById("details-fav")
  };
  var filterInput = document.getElementById("filter-input");
  var filterEmpty = document.getElementById("filter-empty");

  function checkbox(row) { return row.querySelector("input.row-check"); }
  function selected() { return rows.filter(function (r) { return checkbox(r).checked; }); }
  function isDir(row) { return row.dataset.dir === "1"; }

  // Envía un formulario de fila como si lo hubiera enviado el usuario (con su confirmación/prompt)
  function submitForm(f) {
    if (!f) return;
    if (typeof f.requestSubmit === "function") { f.requestSubmit(); return; }
    var ev = new Event("submit", { cancelable: true });
    if (f.dispatchEvent(ev)) f.submit();
  }

  function countText(n) {
    return n === 1 ? t("1 item selected") : t("%(num)s items selected", { num: n });
  }

  function update() {
    var sel = selected();
    var n = sel.length;
    rows.forEach(function (r) { r.classList.toggle("selected", checkbox(r).checked); });
    if (bar) {
      bar.hidden = n === 0;
      barCount.textContent = countText(n);
      bar.querySelectorAll("[data-action]").forEach(function (b) {
        var a = b.dataset.action;
        if (a === "download") b.disabled = n === 0 || sel.some(function (r) { return !r.dataset.zip; });
        if (a === "move" || a === "copy") b.disabled = n === 0;
        if (a === "rename") b.disabled = n !== 1;
        if (a === "delete") b.disabled = n === 0;
      });
    }
    var visible = rows.filter(function (r) { return !r.hidden; });
    if (selectAll) {
      selectAll.checked = n > 0 && n === visible.length;
      selectAll.indeterminate = n > 0 && n < visible.length;
    }
    details.empty.hidden = n !== 0;
    details.multi.hidden = n < 2;
    details.body.hidden = n !== 1;
    if (n >= 2) details.multiCount.textContent = countText(n);
    if (n === 1) {
      var r = sel[0];
      details.name.textContent = r.dataset.name;
      details.kind.textContent = r.dataset.kind;
      details.size.textContent = r.dataset.size;
      details.mtime.textContent = r.dataset.mtime;
      details.icon.querySelector("use").setAttribute("href", isDir(r) ? "#i-folder" : "#i-file");
      details.icon.setAttribute("class", "icon icon-xl " + (isDir(r) ? "folder-icon" : "file-icon"));
      details.open.hidden = !isDir(r) && !r.dataset.view;     // carpetas y archivos que se ven en el visor
      details.open.setAttribute("href", isDir(r) ? r.dataset.href : (r.dataset.view || "#"));
      if (details.download) {
        var link = isDir(r) ? r.dataset.zip : r.dataset.download;  // una carpeta se descarga como ZIP
        details.download.hidden = !link;
        details.download.setAttribute("href", link || "#");
      }
      if (details.fav) {
        var on = r.dataset.fav === "1";
        details.fav.dataset.rel = r.dataset.rel;
        details.fav.classList.toggle("is-on", on);
        details.fav.setAttribute("aria-pressed", on ? "true" : "false");
        details.fav.querySelector("span").textContent = on ? t("Remove from favorites") : t("Add to favorites");
      }
    }
  }

  // Favoritos desde el panel de detalle: se marca o se quita y se recarga (el panel izquierdo cambia)
  if (details.fav) {
    details.fav.addEventListener("click", function () {
      var body = new URLSearchParams({ root: details.fav.dataset.root, path: details.fav.dataset.rel || "" });
      fetch(details.fav.dataset.favUrl, {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf, "Accept": "application/json" }
      }).then(function (res) {
        if (!res.ok) throw new Error(String(res.status));
        window.location.reload();
      }).catch(function () { window.SW.alert(t("Network error.")); });
    });
  }

  function selectOnly(row) {
    rows.forEach(function (r) { checkbox(r).checked = r === row; });
    update();
  }

  // Eventos de una fila: las de la página y las que llegan después (cargar más, filtro en el servidor)
  function wireRow(row) {
    checkbox(row).addEventListener("change", update);
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, label, form")) return;
      selectOnly(row);
    });
    row.addEventListener("dblclick", function (e) {
      if (e.target.closest("a, button, input, label, form")) return;
      if (row.dataset.href) window.location.href = row.dataset.href;
    });
    wireDrag(row);
  }

  if (selectAll) {
    selectAll.addEventListener("change", function () {
      rows.forEach(function (r) { if (!r.hidden) checkbox(r).checked = selectAll.checked; });
      update();
    });
  }

  function deleteMany(sel) {
    window.SW.confirm(t("Delete %(num)s items? This cannot be undone.", { num: sel.length }), { danger: true })
      .then(function (ok) { if (ok) deleteNow(sel); });
  }

  function deleteNow(sel) {
    var forms = sel.map(function (r) { return r.querySelector("form.js-delete"); }).filter(Boolean);
    var chain = Promise.resolve();
    forms.forEach(function (f) {
      chain = chain.then(function () {
        return fetch(f.action, { method: "POST", body: new FormData(f), headers: { "X-CSRF-Token": csrf },
                                 credentials: "same-origin" });
      });
    });
    chain.then(function () { window.location.reload(); },
               function () { window.SW.alert(t("Network error.")).then(function () { window.location.reload(); }); });
  }

  // ------------------------------------------------------------------ descargar (uno, o varios como ZIP)

  function downloadMany(sel) {
    if (sel.length === 1 && !isDir(sel[0]) && sel[0].dataset.download) { window.location.href = sel[0].dataset.download; return; }
    if (sel.length === 1 && sel[0].dataset.zip) { window.location.href = sel[0].dataset.zip; return; }
    var f = document.getElementById("zip-form");
    if (!f) return;
    f.querySelectorAll('input[name="items"]').forEach(function (i) { i.remove(); });
    sel.forEach(function (r) {
      var i = document.createElement("input");
      i.type = "hidden"; i.name = "items"; i.value = r.dataset.rel;
      f.appendChild(i);
    });
    f.submit();  // la respuesta es un adjunto: la página se queda donde está
  }

  // ------------------------------------------------------------------ mover y copiar

  var here = { root: table.dataset.root, path: table.dataset.path || "" };

  function submitTransfer(action, items, destRoot, destPath) {
    var f = document.getElementById("transfer-form");
    if (!f) return;
    f.querySelector('input[name="action"]').value = action;
    f.querySelector('input[name="dest_root"]').value = destRoot;
    f.querySelector('input[name="dest_path"]').value = destPath;
    f.querySelectorAll('input[name="items"]').forEach(function (i) { i.remove(); });
    items.forEach(function (rel) {
      var i = document.createElement("input");
      i.type = "hidden"; i.name = "items"; i.value = rel;
      f.appendChild(i);
    });
    f.submit();
  }

  var picker = document.getElementById("pick-dest");
  var pick = { action: "move", items: [], root: here.root, path: here.path, roots: null };

  function encodePath(p) { return p.split("/").filter(Boolean).map(encodeURIComponent).join("/"); }

  // Por qué no se pueden poner aquí ("" = sí se puede)
  function pickProblem() {
    var r = (pick.roots || []).find(function (x) { return x.name === pick.root; });
    if (!r) return t("You cannot write in this folder.");
    var perms = r.permissions;
    var inside = pick.root === here.root && pick.items.some(function (rel) {
      return pick.path === rel || pick.path.indexOf(rel + "/") === 0;
    });
    if (inside) return t("A folder cannot go inside itself.");
    if (pick.action === "move" && pick.root === here.root) {
      if (pick.path === here.path) return t("They are already in this folder: choose another one.");
      return perms.indexOf("rename") !== -1 ? "" : t("You cannot write in this folder.");
    }
    return perms.indexOf("upload") !== -1 ? "" : t("You cannot write in this folder.");
  }
  function pickAllowed() { return !pickProblem(); }

  function renderPicker() {
    var list = document.getElementById("pick-list");
    var crumbs = document.getElementById("pick-crumbs");
    var ok = document.getElementById("pick-ok");
    var note = document.getElementById("pick-note");
    document.getElementById("pick-root").value = pick.root;
    crumbs.innerHTML = "";
    var parts = pick.path.split("/").filter(Boolean);
    var top = document.createElement("button");
    top.type = "button";
    top.textContent = "/";
    top.addEventListener("click", function () { pick.path = ""; renderPicker(); });
    crumbs.appendChild(top);
    parts.forEach(function (part, i) {
      var sep = document.createElement("span");
      sep.className = "sep"; sep.textContent = "›";
      var b = document.createElement("button");
      b.type = "button"; b.textContent = part;
      b.addEventListener("click", function () { pick.path = parts.slice(0, i + 1).join("/"); renderPicker(); });
      crumbs.appendChild(sep);
      crumbs.appendChild(b);
    });
    var problem = pickProblem();
    ok.disabled = !!problem;
    note.hidden = !problem;
    note.textContent = problem;
    list.innerHTML = '<li class="muted">' + t("Loading…") + "</li>";
    var url = picker.dataset.browse.replace("ROOTNAME", encodeURIComponent(pick.root)) + encodePath(pick.path);
    fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        list.innerHTML = "";
        var dirs = (data.entries || []).filter(function (e) { return e.type === "dir"; });
        if (pick.path) {
          var up = document.createElement("li");
          var ub = document.createElement("button");
          ub.type = "button"; ub.textContent = "↑ ..";
          ub.addEventListener("click", function () { pick.path = parts.slice(0, -1).join("/"); renderPicker(); });
          up.appendChild(ub);
          list.appendChild(up);
        }
        dirs.forEach(function (e) {
          var li = document.createElement("li");
          var b = document.createElement("button");
          b.type = "button";
          b.innerHTML = '<svg class="icon icon-sm folder-icon" aria-hidden="true"><use href="#i-folder"></use></svg>';
          b.appendChild(document.createTextNode(e.name));
          b.addEventListener("click", function () { pick.path = e.path; renderPicker(); });
          li.appendChild(b);
          list.appendChild(li);
        });
        if (!dirs.length && !pick.path) list.innerHTML = '<li class="muted">' + t("No subfolders.") + "</li>";
      }, function () {
        list.innerHTML = '<li class="muted">' + t("Could not read this folder.") + "</li>";
      });
  }

  function openPicker(action, sel) {
    if (!picker || !sel.length) return;
    pick.action = action;
    pick.items = sel.map(function (r) { return r.dataset.rel; });
    pick.root = here.root;
    pick.path = here.path;
    var n = sel.length;
    document.getElementById("pick-title").textContent = action === "move"
      ? (n === 1 ? t("Move «%(name)s» to…", { name: sel[0].dataset.name }) : t("Move %(num)s items to…", { num: n }))
      : (n === 1 ? t("Copy «%(name)s» to…", { name: sel[0].dataset.name }) : t("Copy %(num)s items to…", { num: n }));
    document.getElementById("pick-ok").textContent = action === "move" ? t("Move here") : t("Copy here");
    var load = pick.roots ? Promise.resolve(pick.roots)
      : fetch(picker.dataset.roots, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
          .then(function (r) { return r.json(); }).then(function (d) { pick.roots = d.roots || []; return pick.roots; });
    load.then(function (roots) {
      var select = document.getElementById("pick-root");
      select.innerHTML = "";
      roots.forEach(function (r) {
        var o = document.createElement("option");
        o.value = r.name; o.textContent = r.label + (r.read_only ? " (" + t("read-only") + ")" : "");
        select.appendChild(o);
      });
      renderPicker();
      picker.showModal();
    });
  }

  if (picker) {
    document.getElementById("pick-root").addEventListener("change", function (e) {
      pick.root = e.target.value; pick.path = ""; renderPicker();
    });
    document.getElementById("pick-cancel").addEventListener("click", function () { picker.close(); });
    document.getElementById("pick-ok").addEventListener("click", function () {
      if (!pickAllowed()) return;
      picker.close();
      submitTransfer(pick.action, pick.items, pick.root, pick.path);
    });
  }

  // ------------------------------------------------------------------ arrastrar filas a una carpeta (Ctrl: copiar)

  var DRAG_TYPE = "application/x-storageweb-items";
  var dragging = null;

  function wireDrag(row) {
    if (row.getAttribute("draggable") !== "true") return;
    row.addEventListener("dragstart", function (e) {
      if (!checkbox(row).checked) selectOnly(row);
      dragging = selected().map(function (r) { return r.dataset.rel; });
      e.dataTransfer.effectAllowed = "copyMove";
      e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(dragging));
      e.dataTransfer.setData("text/plain", selected().map(function (r) { return r.dataset.name; }).join("\n"));
    });
    row.addEventListener("dragend", function () { dragging = null; });
  }
  rows.forEach(wireRow);

  function dropTarget(el) {
    var row = el.closest("tr.file-row");
    if (row && isDir(row) && !checkbox(row).checked) return { el: row, root: here.root, path: row.dataset.rel };
    var item = el.closest(".tree-item[data-drop-root]");
    if (item) return { el: item, root: item.dataset.dropRoot, path: item.dataset.dropPath || "" };
    return null;
  }

  function clearTargets() {
    document.querySelectorAll(".drop-target").forEach(function (x) { x.classList.remove("drop-target"); });
  }

  document.addEventListener("dragover", function (e) {
    if (!dragging) return;
    var target = dropTarget(e.target);
    clearTargets();
    if (!target) return;
    var copy = e.ctrlKey || e.altKey;
    if (!copy && target.root === here.root && target.path === here.path) return;  // ya están aquí
    e.preventDefault();
    e.dataTransfer.dropEffect = copy ? "copy" : "move";
    target.el.classList.add("drop-target");
  });
  document.addEventListener("dragleave", function (e) {
    if (dragging && e.target.classList && e.target.classList.contains("drop-target")) e.target.classList.remove("drop-target");
  });
  document.addEventListener("drop", function (e) {
    if (!dragging) return;
    var target = dropTarget(e.target);
    clearTargets();
    if (!target) return;
    e.preventDefault();
    var items = dragging;
    dragging = null;
    submitTransfer(e.ctrlKey || e.altKey ? "copy" : "move", items, target.root, target.path);
  });

  function runAction(action) {
    var sel = selected();
    if (action === "clear") { rows.forEach(function (r) { checkbox(r).checked = false; }); update(); return; }
    if (!sel.length) return;
    if (action === "download") downloadMany(sel);
    if (action === "move" || action === "copy") openPicker(action, sel);
    if (action === "rename" && sel.length === 1) submitForm(sel[0].querySelector("form.js-rename"));
    if (action === "delete") {
      if (sel.length === 1) submitForm(sel[0].querySelector("form.js-delete"));
      else deleteMany(sel);
    }
  }

  document.querySelectorAll("#selection-bar [data-action], #details [data-action]").forEach(function (b) {
    b.addEventListener("click", function () { runAction(b.dataset.action); });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && selected().length && !e.target.closest("input, textarea, select")) runAction("clear");
  });

  // ------------------------------------------------------------------ carpetas que no caben en la página
  // (storage.page_size / listing_mode, files._listing): «scroll» carga más filas al bajar; con el filtro, las
  // filas que coinciden las da el servidor (entre todas las de la carpeta), también por trozos
  var foot = document.getElementById("listing-foot");
  var tbody = table.tBodies[0];
  var pager = document.getElementById("listing-pager");
  var loadMoreBtn = document.getElementById("load-more");
  var statusEl = document.getElementById("listing-status");
  var initialStatus = statusEl ? statusEl.textContent : "";
  var mode = foot ? foot.dataset.mode : "";
  var nextRows = foot ? foot.dataset.next : "";
  var query = filterInput ? filterInput.value.trim() : "";
  var total = foot ? parseInt(foot.dataset.total, 10) || 0 : 0;
  var loading = false;
  var seq = 0;

  function canLoadMore() { return !!nextRows && (mode === "scroll" || query !== ""); }

  function refreshFoot() {
    if (!foot) return;
    if (pager) pager.hidden = mode !== "pages" || query !== "";
    if (loadMoreBtn) loadMoreBtn.hidden = !canLoadMore();
    if (statusEl && (mode === "scroll" || query !== "")) {
      statusEl.textContent = query
        ? t("%(shown)s of %(total)s items match «%(query)s»", { shown: rows.length, total: total, query: query })
        : t("%(shown)s of %(total)s items", { shown: rows.length, total: total });
    } else if (statusEl) {
      statusEl.textContent = initialStatus;
    }
    if (filterEmpty) filterEmpty.hidden = rows.length > 0 || query === "";
  }

  function fetchRows(url) {
    return fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text().then(function (html) {
        return { html: html, next: r.headers.get("X-Next") || "", total: parseInt(r.headers.get("X-Total"), 10) || 0 };
      });
    });
  }

  function putRows(html, replace) {
    var tpl = document.createElement("template");
    tpl.innerHTML = html;
    if (replace) {
      rows.forEach(function (r) { r.remove(); });
      rows = [];
    }
    var empty = tbody.querySelector("tr.row-empty");
    if (empty) empty.remove();
    Array.prototype.forEach.call(tpl.content.querySelectorAll("tr.file-row"), function (row) {
      tbody.appendChild(row);
      rows.push(row);
      wireRow(row);
      row.querySelectorAll("form.js-rename").forEach(wireRename);
      row.querySelectorAll("form.js-confirm").forEach(window.SW.confirmForm);
    });
    update();
  }

  function loadMore() {
    if (loading || !canLoadMore()) return;
    loading = true;
    var mine = seq;
    fetchRows(nextRows).then(function (res) {
      if (mine !== seq) return;          // el filtro cambió mientras tanto
      putRows(res.html, false);
      nextRows = res.next;
      total = res.total;
      refreshFoot();
      return true;
    }).catch(function () { window.SW.alert(t("Network error.")); return false; })
      .then(function (ok) {
        loading = false;
        // El observador solo avisa al entrar en la vista: si tras cargar el botón sigue cerca, se carga otro trozo
        if (ok && mine === seq && loadMoreBtn && !loadMoreBtn.hidden &&
            loadMoreBtn.getBoundingClientRect().top < window.innerHeight + 600) loadMore();
      });
  }

  if (foot) {
    if (mode === "scroll" && pager) pager.hidden = true;   // sin JavaScript, el paginador
    if (loadMoreBtn) {
      loadMoreBtn.addEventListener("click", loadMore);
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (entries) {
          if (entries[0].isIntersecting) loadMore();
        }, { rootMargin: "600px 0px" }).observe(loadMoreBtn);
      }
    }
    refreshFoot();
  }

  // El filtro: en una carpeta entera en la página, al momento sobre las filas; si no, pregunta al servidor
  var filterTimer = null;
  function serverFilter() {
    var mine = ++seq;
    loading = false;
    // Sin filtro, vuelve a lo de antes: la página del paginador o el principio
    var url = foot.dataset.filter + (query ? "&q=" + encodeURIComponent(query)
      : (mode === "pages" ? "&page=" + foot.dataset.page : ""));
    fetchRows(url).then(function (res) {
      if (mine !== seq) return;
      putRows(res.html, true);
      nextRows = res.next;
      total = res.total;
      refreshFoot();
    }).catch(function () { window.SW.alert(t("Network error.")); });
  }

  if (filterInput) {
    filterInput.addEventListener("input", function () {
      if (foot) {
        query = filterInput.value.trim();
        clearTimeout(filterTimer);
        filterTimer = setTimeout(serverFilter, 250);
        return;
      }
      var q = filterInput.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (r) {
        var match = !q || r.dataset.name.toLowerCase().indexOf(q) !== -1;
        r.hidden = !match;
        if (!match) checkbox(r).checked = false;
        if (match) shown++;
      });
      if (filterEmpty) filterEmpty.hidden = shown > 0 || rows.length === 0;
      update();
    });
  }

  update();
})();

(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var input = document.getElementById("file-input");
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

  function uploadFile(file, ui) {
    var api = form.dataset.api;
    // Clave para reanudar la misma subida tras recargar la página
    var key = "sw-upload:" + [form.dataset.root, form.dataset.path, file.name, file.size, file.lastModified].join("|");
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
      return request("POST", api, { root: form.dataset.root, path: form.dataset.path,
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

  function uploadAll(files) {
    if (!files || !files.length || !form) return;
    var maxFile = parseInt(form.dataset.maxFile, 10) || 0;
    var list = Array.prototype.slice.call(files);
    var tooBig = list.filter(function (f) { return maxFile && f.size > maxFile; });
    if (tooBig.length) {
      list = list.filter(function (f) { return tooBig.indexOf(f) < 0; });
      window.SW.alert(t("These files exceed the maximum size allowed (%(max)s):", {max: fmt(maxFile)}) + "\n" +
                      tooBig.map(function (f) { return f.name; }).join("\n"))
        .then(function () { if (list.length) startUpload(list); });
      return;
    }
    startUpload(list);
  }

  function startUpload(list) {

    var total = list.reduce(function (s, f) { return s + f.size; }, 0) || 1;
    var done = 0, errors = [], bar = panel.querySelector(".bar"),
        label = panel.querySelector(".label"), detail = panel.querySelector(".detail");
    current.cancelled = false;
    panel.hidden = false;
    if (input) input.disabled = true;
    window.onbeforeunload = function () { return t("An upload is in progress"); };

    var chain = Promise.resolve();
    list.forEach(function (file, i) {
      chain = chain.then(function () {
        if (current.cancelled) return;
        detail.textContent = t("File %(index)s of %(total)s: %(name)s", {index: i + 1, total: list.length, name: file.name});
        return uploadFile(file, function (bytes) {
          var pct = Math.min(100, Math.floor(((done + bytes) / total) * 100));
          bar.style.width = pct + "%";
          label.textContent = pct + "% · " + fmt(done + bytes) + " / " + fmt(total);
        }).then(function () { done += file.size; }, function (err) {
          if (err.status === -1) return;
          errors.push(file.name + ": " + errorText(err));
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

  if (dropzone) {
    ["dragenter", "dragover"].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
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
      if (e.dataTransfer && e.dataTransfer.files.length) uploadAll(e.dataTransfer.files);
    });
  }

  // ------------------------------------------------------------------ acciones de la tabla

  document.querySelectorAll("form.js-rename").forEach(function (f) {
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
    download: document.getElementById("details-download")
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
        if (a === "download") b.disabled = !(n === 1 && !isDir(sel[0]) && sel[0].dataset.href);
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
      details.open.hidden = !isDir(r);
      details.open.setAttribute("href", isDir(r) ? r.dataset.href : "#");
      if (details.download) {
        details.download.hidden = isDir(r) || !r.dataset.href;
        details.download.setAttribute("href", r.dataset.href || "#");
      }
    }
  }

  function selectOnly(row) {
    rows.forEach(function (r) { checkbox(r).checked = r === row; });
    update();
  }

  rows.forEach(function (row) {
    checkbox(row).addEventListener("change", update);
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, label, form")) return;
      selectOnly(row);
    });
    row.addEventListener("dblclick", function (e) {
      if (e.target.closest("a, button, input, label, form")) return;
      if (row.dataset.href) window.location.href = row.dataset.href;
    });
  });

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

  function runAction(action) {
    var sel = selected();
    if (action === "clear") { rows.forEach(function (r) { checkbox(r).checked = false; }); update(); return; }
    if (!sel.length) return;
    if (action === "download" && sel.length === 1 && sel[0].dataset.href) window.location.href = sel[0].dataset.href;
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

  if (filterInput) {
    filterInput.addEventListener("input", function () {
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

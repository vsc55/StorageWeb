// Explorador: subir archivos y carpetas (botones, o arrastrando desde el equipo) por la API de subidas por partes
// (web/api/uploads.py): reanuda tras recargar la página, reintenta con espera creciente y se puede cancelar. No
// depende de la tabla ni del núcleo (app.js).
(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var input = document.getElementById("file-input");
  var folderInput = document.getElementById("folder-input");
  var dropzone = document.getElementById("dropzone");
  var panel = document.getElementById("upload-panel");
  if (!form) return;
  var csrf = window.SW.csrf;
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

  var store = window.SW.store;

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
    if (!files || !files.length) return;
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

  if (panel) {
    document.getElementById("upload-cancel").addEventListener("click", function () {
      window.SW.confirm(t("Cancel the upload?"), { danger: true }).then(function (ok) {
        if (ok) cancelUpload();
      });
    });
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
})();

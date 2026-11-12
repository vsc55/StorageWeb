(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var input = document.getElementById("file-input");
  var dropzone = document.getElementById("dropzone");
  var panel = document.getElementById("upload-panel");
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  // Traducciones: el servidor entrega {texto_fuente: traducción} en <script id="i18n-messages">
  var MESSAGES = {};
  try { MESSAGES = JSON.parse(document.getElementById("i18n-messages").textContent); } catch (e) { MESSAGES = {}; }
  function t(message, params) {
    var text = MESSAGES[message] || message;
    return text.replace(/%\((\w+)\)s/g, function (m, key) {
      return params && params[key] !== undefined ? params[key] : m;
    });
  }

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
      alert(t("These files exceed the maximum size allowed (%(max)s):", {max: fmt(maxFile)}) + "\n" +
            tooBig.map(function (f) { return f.name; }).join("\n"));
      list = list.filter(function (f) { return tooBig.indexOf(f) < 0; });
      if (!list.length) return;
    }

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
      if (errors.length) alert(t("Could not upload:") + "\n" + errors.join("\n"));
      window.location.reload();
    });
  }

  if (panel) {
    document.getElementById("upload-cancel").addEventListener("click", function () {
      if (!confirm(t("Cancel the upload?"))) return;
      current.cancelled = true;
      if (current.xhr) current.xhr.abort();
      if (current.id) {
        var xhr = new XMLHttpRequest();
        xhr.open("DELETE", form.dataset.api + "/" + current.id);
        xhr.setRequestHeader("X-CSRF-Token", csrf);
        xhr.send();
      }
    });
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

  document.querySelectorAll("form.js-confirm").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!confirm(f.dataset.confirm || t("Are you sure?"))) e.preventDefault();
    });
  });

  document.querySelectorAll("form.js-rename").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var name = prompt(t("New name:"), f.dataset.name);
      if (!name || name === f.dataset.name) { e.preventDefault(); return; }
      f.querySelector('input[name="name"]').value = name;
    });
  });
})();

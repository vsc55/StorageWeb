(function () {
  "use strict";

  var form = document.getElementById("upload-form");
  var input = document.getElementById("file-input");
  var dropzone = document.getElementById("dropzone");
  var progress = document.getElementById("progress");
  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");

  function upload(files) {
    if (!files || !files.length || !form) return;
    var maxBytes = parseInt(form.dataset.maxMb, 10) * 1024 * 1024;
    var total = 0;
    var data = new FormData();
    for (var i = 0; i < files.length; i++) {
      total += files[i].size;
      data.append("files", files[i], files[i].name);
    }
    if (total > maxBytes) {
      alert("El tamaño total supera el máximo permitido (" + form.dataset.maxMb + " MB).");
      return;
    }
    var bar = progress.querySelector(".bar");
    var label = progress.querySelector(".label");
    progress.hidden = false;
    bar.style.width = "0%";
    label.textContent = "Subiendo " + files.length + " archivo(s)…";

    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        var pct = Math.round((e.loaded / e.total) * 100);
        bar.style.width = pct + "%";
        label.textContent = pct + "%";
      }
    };
    xhr.onload = function () {
      var msg = "";
      try {
        var res = JSON.parse(xhr.responseText);
        if (res.errors && res.errors.length) msg = "Errores:\n" + res.errors.join("\n");
      } catch (err) {
        if (xhr.status === 413) msg = "El archivo es demasiado grande.";
        else if (xhr.status >= 400) msg = "Error al subir (HTTP " + xhr.status + ").";
      }
      if (msg) alert(msg);
      window.location.reload();
    };
    xhr.onerror = function () {
      alert("Error de red durante la subida.");
      progress.hidden = true;
    };
    xhr.send(data);
  }

  if (input) {
    input.addEventListener("change", function () { upload(input.files); });
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
      if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files);
    });
  }

  document.querySelectorAll("form.js-delete").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var what = f.dataset.dir === "1" ? "la carpeta «" + f.dataset.name + "» y todo su contenido" : "«" + f.dataset.name + "»";
      if (!confirm("¿Eliminar " + what + "?")) e.preventDefault();
    });
  });

  document.querySelectorAll("form.js-rename").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var name = prompt("Nuevo nombre:", f.dataset.name);
      if (!name || name === f.dataset.name) { e.preventDefault(); return; }
      f.querySelector('input[name="name"]').value = name;
    });
  });
})();

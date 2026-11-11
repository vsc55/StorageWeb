(function () {
  "use strict";

  // Confirmación genérica para formularios destructivos
  document.querySelectorAll("form.js-confirm").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!confirm(f.dataset.confirm || "¿Seguro?")) e.preventDefault();
    });
  });

  // Tabla de carpetas compartidas: añadir y quitar filas
  var table = document.getElementById("shares-table");
  var tpl = document.getElementById("share-row-template");
  var addBtn = document.getElementById("add-share");
  if (table && tpl && addBtn) {
    addBtn.addEventListener("click", function () {
      var row = tpl.content.firstElementChild.cloneNode(true);
      table.querySelector("tbody").appendChild(row);
      row.querySelector("input").focus();
    });
    table.addEventListener("click", function (e) {
      if (e.target.classList.contains("js-remove-row")) {
        e.target.closest("tr").remove();
      }
    });
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

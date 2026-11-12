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

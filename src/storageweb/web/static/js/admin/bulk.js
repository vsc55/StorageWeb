// Selección múltiple y acciones en bloque (usuarios, sesiones).
(function () {
  "use strict";
  var t = window.SW.t;

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
})();

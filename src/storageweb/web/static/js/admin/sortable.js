// Tablas que se ordenan al pulsar una cabecera, ascendente y descendente (table.js-sortable). Cada <th data-sort>
// dice cómo se compara su columna: «text» (sin distinguir mayúsculas ni tildes), «number» o «version» (1.10 va
// después de 1.9). El valor es el texto de la celda o, si lo trae, su data-sort-value. Lo vacío va siempre al final.
// Las cabeceras pasan a ser botones (teclado y lectores de pantalla) y llevan aria-sort.
(function () {
  "use strict";

  var t = window.SW.t;
  var collator = new Intl.Collator(document.documentElement.lang || undefined, { numeric: true, sensitivity: "base" });

  function valueOf(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    return cell.hasAttribute("data-sort-value") ? cell.getAttribute("data-sort-value") : cell.textContent.trim();
  }

  function compare(type, a, b) {
    var emptyA = a === "" || a === "—", emptyB = b === "" || b === "—";
    if (emptyA || emptyB) return emptyA === emptyB ? 0 : (emptyA ? 1 : -1);   // lo vacío, al final
    if (type === "number") {
      var x = parseFloat(a), y = parseFloat(b);
      if (!isNaN(x) && !isNaN(y)) return x - y;
    }
    return collator.compare(a, b);      // «version» también: la comparación numérica ordena 1.9 < 1.10
  }

  function sortBy(table, th, descending) {
    var index = th.cellIndex;
    var type = th.dataset.sort || "text";
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (r1, r2) {
      var empty1 = valueOf(r1, index), empty2 = valueOf(r2, index);
      var result = compare(type, empty1, empty2);
      // Lo vacío sigue al final también en descendente
      var blank = empty1 === "" || empty1 === "—" || empty2 === "" || empty2 === "—";
      return descending && !blank ? -result : result;
    });
    rows.forEach(function (row) { body.appendChild(row); });
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (cell) {
      if (cell.hasAttribute("data-sort")) cell.setAttribute("aria-sort", "none");
    });
    th.setAttribute("aria-sort", descending ? "descending" : "ascending");
  }

  function wire(table) {
    if (!table.tHead || !table.tBodies.length || table.dataset.sortable === "1") return;
    table.dataset.sortable = "1";
    Array.prototype.forEach.call(table.tHead.querySelectorAll("th[data-sort]"), function (th) {
      var label = th.textContent.trim();
      var button = document.createElement("button");
      button.type = "button";
      button.className = "sort-btn";
      button.title = t("Sort by %(column)s", { column: label });
      while (th.firstChild) button.appendChild(th.firstChild);
      th.appendChild(button);
      th.setAttribute("aria-sort", "none");
      button.addEventListener("click", function () {
        // Primera vez, ascendente; después, alterna
        sortBy(table, th, th.getAttribute("aria-sort") === "ascending");
      });
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("table.js-sortable"), wire);
  // Para las tablas que llegan después sin recargar la página (p. ej. Personas → Importar mientras se escribe)
  window.SW.sortable = function (root) {
    Array.prototype.forEach.call((root || document).querySelectorAll("table.js-sortable"), wire);
  };
})();

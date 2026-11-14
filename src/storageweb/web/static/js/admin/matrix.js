// Matriz de accesos: color de cada celda según el nivel.
(function () {
  "use strict";
  var t = window.SW.t;

  // Matriz de accesos: color de cada celda según el nivel (la barra de guardar es la común)
  var matrix = document.getElementById("access-matrix");
  if (matrix) {
    var paint = function (sel) {
      sel.classList.remove("access-none", "access-read", "access-write");
      sel.classList.add("access-" + sel.value);
      sel.classList.toggle("changed", sel.value !== sel.dataset.initial);
    };
    var paintAll = function () { matrix.querySelectorAll("select.access").forEach(paint); };
    matrix.addEventListener("change", function (e) { if (e.target.classList.contains("access")) paint(e.target); });
    matrix.addEventListener("swrestore", function (e) { if (e.target.classList.contains("access")) paint(e.target); });
    matrix.addEventListener("reset", function () { setTimeout(paintAll, 0); });
    paintAll();
  }
})();

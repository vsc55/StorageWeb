// Explorador: las miniaturas de las imágenes en la lista (filas con data-thumb, files.thumbnail). Cada una carga
// cuando su fila llega a la pantalla (loading=lazy) y sustituye al icono; si no hay miniatura (404, una imagen rota
// o demasiado grande), se queda el icono. Engancha también las filas que llegan después (cargar más, el filtro).
(function () {
  "use strict";

  if (!window.SW || !window.SW.files) return;

  window.SW.files.onRow(function (row) {
    var url = row.dataset.thumb;
    var cell = row.querySelector(".name-cell");
    if (!url || !cell || cell.querySelector("img.row-thumb")) return;
    var img = document.createElement("img");
    img.className = "row-thumb";
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.addEventListener("load", function () { cell.classList.add("has-thumb"); });
    img.addEventListener("error", function () { img.remove(); cell.classList.remove("has-thumb"); });
    cell.insertBefore(img, cell.firstChild);
    img.src = url;
  });
})();

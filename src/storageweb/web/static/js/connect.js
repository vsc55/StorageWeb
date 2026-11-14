// Conectar una aplicación (/connect/<cliente>): al terminar, vuelve a la aplicación sola (vscode://…).
// Si el navegador no la abre sin un clic, queda el botón.
"use strict";
(function () {
  var link = document.getElementById("connect-return");
  if (link && link.getAttribute("data-auto") === "1") {
    window.location.href = link.href;
  }
})();

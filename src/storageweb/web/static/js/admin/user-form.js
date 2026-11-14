// Ficha de usuario: la contraseña solo aplica a usuarios locales.
(function () {
  "use strict";
  var t = window.SW.t;

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

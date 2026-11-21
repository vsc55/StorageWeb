// Ficha de usuario: la contraseña solo aplica a usuarios locales (alta), y la barra «Cambios sin guardar» de lo
// editable (campos con form="user-form", repartidos por tarjetas que también tienen botones inmediatos).
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

  // Ficha: la barra de guardar aparece solo si algo cambió, y desaparece si se deja como estaba (o con Descartar).
  // Salir con cambios (otro enlace, o un botón inmediato como añadir un grupo) avisa antes de perderlos.
  var form = document.getElementById("user-form");
  var bar = document.querySelector("[data-user-save]");
  if (!form || !bar) return;
  var state = function () {
    return Array.prototype.map.call(form.elements, function (el) {
      if (!el.name || el.name === "_csrf") return "";
      return el.name + "=" + (el.type === "checkbox" ? el.checked : el.value);
    }).join("&");
  };
  var initial = state();
  var submitting = false;
  var dirty = function () { return state() !== initial; };
  var refresh = function () {
    bar.classList.toggle("is-idle", !dirty());
    var label = bar.querySelector("[data-user-save-status]");
    if (label) label.textContent = t("Unsaved changes");
  };
  document.addEventListener("input", function (e) { if (e.target.form === form) refresh(); });
  document.addEventListener("change", function (e) { if (e.target.form === form) refresh(); });
  form.addEventListener("reset", function () { setTimeout(refresh, 0); });
  form.addEventListener("submit", function () { submitting = true; });
  window.addEventListener("beforeunload", function (e) {
    if (submitting || !dirty()) return;
    e.preventDefault();
    e.returnValue = "";
  });
  refresh();
})();

// Entra ID: registro con código de dispositivo (consulta periódica).
(function () {
  "use strict";
  var t = window.SW.t;

  // Registro en Entra ID: consulta cada pocos segundos si el administrador ya inició sesión
  var regStatus = document.getElementById("register-status");
  var regForm = document.getElementById("register-poll-form");
  if (regStatus && regForm && window.fetch) {
    var csrf = regForm.querySelector("input[name=_csrf]").value;
    var wait = (parseInt(regStatus.dataset.interval, 10) || 5) * 1000;
    var poll = function () {
      fetch(regStatus.dataset.pollUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Accept": "application/json", "X-CSRF-Token": csrf }
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (data.status === "pending") {
          if (data.interval) wait = data.interval * 1000;
          regStatus.textContent = data.message || t("Waiting for you to sign in…");
          setTimeout(poll, wait);
        } else if (data.status === "complete") {
          regStatus.textContent = t("Signed in. Registering the application in Entra ID…");
          window.location.href = data.redirect;
        } else {
          regStatus.classList.add("is-error");
          regStatus.textContent = data.message;
        }
      }).catch(function () { setTimeout(poll, wait * 2); });
    };
    setTimeout(poll, wait);
  }
})();

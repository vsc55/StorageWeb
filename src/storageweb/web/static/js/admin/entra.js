// Entra ID: registro con código de dispositivo (consulta periódica).
(function () {
  "use strict";
  var t = window.SW.t;

  // Registro en Entra ID: consulta cada pocos segundos si el administrador ya inició sesión
  var regStatus = document.getElementById("register-status");
  var regForm = document.getElementById("register-poll-form");
  if (regStatus && regForm && window.fetch) {
    var wait = (parseInt(regStatus.dataset.interval, 10) || 5) * 1000;
    var poll = function () {
      window.SW.getJSON(regStatus.dataset.pollUrl, { method: "POST" }).then(function (data) {
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
  // Asistente, paso 4: un secreto recién creado que Microsoft todavía no acepta se vuelve a comprobar solo
  var recheck = document.getElementById("entra-recheck");
  if (recheck) {
    setTimeout(function () { window.location.reload(); }, (parseInt(recheck.dataset.recheck, 10) || 8) * 1000);
  }
})();

// Entra ID: registro con código de dispositivo (consulta periódica) y búsqueda de grupos por nombre.
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

  // Alta de grupo: buscar grupos de Entra ID por nombre y rellenar el Object ID
  var extInput = document.querySelector("input[data-entra-search]");
  if (extInput && window.fetch) {
    var list = document.getElementById(extInput.getAttribute("list"));
    var labelInput = document.querySelector("input[name=label]");
    var timer = null;
    var lastGroups = [];
    var isEntra = function () {
      var checked = document.querySelector("input[name=source]:checked");
      return checked && checked.value === "entra";
    };
    extInput.addEventListener("input", function () {
      clearTimeout(timer);
      var found = lastGroups.find(function (g) { return g.id === extInput.value; });
      if (found) {
        if (labelInput && !labelInput.value) labelInput.value = found.name;
        return;
      }
      if (!isEntra() || extInput.value.length < 2 || /^[0-9a-f-]{36}$/i.test(extInput.value)) return;
      timer = setTimeout(function () {
        fetch(extInput.dataset.entraSearch + "?q=" + encodeURIComponent(extInput.value), {
          headers: { "Accept": "application/json" }, credentials: "same-origin"
        }).then(function (r) { return r.json(); }).then(function (data) {
          lastGroups = data.groups || [];
          list.innerHTML = "";
          lastGroups.forEach(function (g) {
            var opt = document.createElement("option");
            opt.value = g.id;
            opt.label = g.name;
            opt.textContent = g.name;
            list.appendChild(opt);
          });
        }).catch(function () {});
      }, 300);
    });
  }
})();

// Seguridad → Contraseñas: el probador. Envía la contraseña escrita (y el usuario, si lo hay) con las reglas que hay
// en la página ahora, guardadas o no (el formulario de ajustes entero, from_page=1), a settings.password_test, que
// contesta con cada regla (ok: true / false / null = sin comprobar) y lo pinta como lista. No guarda nada, y no es un
// <form> ni un type="password" para que el navegador no ofrezca guardar la contraseña. La lista y la barra de fortaleza
// se pintan con SW.paintChecks / SW.paintStrength (password-meter.js); «Generar» pide una que cumpla esas reglas. Se
// prueba sola mientras se escribe (y al cambiar las reglas), salvo las filtraciones conocidas, que van a internet: esas,
// con el botón «Probar».
(function () {
  "use strict";

  var form = document.querySelector(".password-test-form");
  if (!form) return;
  var t = window.SW.t;
  var box = document.querySelector(".password-test-result");
  var summary = box.querySelector(".password-test-summary");
  var list = box.querySelector(".password-checks");
  var password = form.querySelector('input[name="test_password"]');
  var settingsForm = document.querySelector("form.settings-form");
  // El campo del usuario solo tiene sentido con la regla del nombre de usuario (la casilla de la página)
  var nameRule = settingsForm && settingsForm.querySelector('input[name="password_reject_username"]');
  var nameField = form.querySelector(".js-test-username");
  if (nameRule && nameField) {
    nameRule.addEventListener("change", function () { nameField.hidden = !nameRule.checked; });
  }
  var button = form.querySelector(".js-try");

  // Se ve con puntos (CSS) salvo que se pida verla: nunca type="password", que el navegador ofrecería guardar
  form.querySelector(".js-show-password").addEventListener("change", function (event) {
    password.classList.toggle("is-masked", !event.target.checked);
  });

  var strength = box.querySelector(".pw-strength");

  function paint(data) {
    window.SW.paintChecks(list, data.checks);
    window.SW.paintStrength(strength, data.checks.length ? data : null);
    summary.textContent = data.summary;
    summary.className = "password-test-summary " + (data.ok ? "text-ok" : "text-danger");
    box.hidden = false;
  }

  function body(live) {
    var data = settingsForm ? new FormData(settingsForm) : new FormData();
    if (live) data.append("live", "1");      // mientras se escribe: sin ir a internet (filtraciones)
    form.querySelectorAll("input[name]").forEach(function (input) { data.append(input.name, input.value); });
    if (settingsForm) data.append("from_page", "1");
    return data;
  }

  // ``quiet``: la comprobación mientras se escribe (sin mover el foco ni desactivar el botón). Una respuesta que llega
  // tarde (de lo que se escribía antes) se descarta
  var seq = 0;
  var timer = null;
  function run(quiet) {
    if (!password.value) {
      if (quiet) { ++seq; box.hidden = true; } else { password.focus(); }
      return;
    }
    var mine = ++seq;
    if (!quiet) button.disabled = true;
    window.SW.getJSON(form.dataset.action, { method: "POST", body: body(quiet) })
      .then(function (data) { if (mine === seq) paint(data); })
      .catch(function () {
        if (mine !== seq) return;
        list.innerHTML = "";
        summary.textContent = t("Network error.");
        summary.className = "password-test-summary text-danger";
        box.hidden = false;
      })
      .finally(function () { button.disabled = false; });
  }
  function later() {
    clearTimeout(timer);
    timer = setTimeout(function () { run(true); }, 250);
  }

  button.addEventListener("click", function () { run(false); });
  // En tiempo real: al escribir la contraseña o el usuario, y al cambiar las reglas de la otra pestaña
  password.addEventListener("input", later);
  if (nameField) nameField.querySelector("input").addEventListener("input", function () { if (password.value) later(); });
  if (settingsForm) {
    ["input", "change"].forEach(function (type) {
      settingsForm.addEventListener(type, function () { if (password.value) later(); });
    });
  }
  // Generar: una aleatoria con las reglas que hay en la página (guardadas o no), a la vista y ya probada
  form.querySelector(".js-generate").addEventListener("click", function () {
    window.SW.getJSON(form.dataset.generate, { method: "POST", body: body() })
      .then(function (data) {
        password.value = data.password;
        password.classList.remove("is-masked");
        form.querySelector(".js-show-password").checked = true;
        run(false);
      })
      .catch(function () { window.SW.alert(t("No password could be generated with the current rules.")); });
  });
  form.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.tagName === "INPUT" && event.target.type === "text") {
      event.preventDefault();
      run(false);
    }
  });
})();

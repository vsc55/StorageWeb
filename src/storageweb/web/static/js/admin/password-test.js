// Seguridad → Contraseñas: el probador. Envía la contraseña escrita (y el usuario, si lo hay) con las reglas que hay
// en la página ahora, guardadas o no (el formulario de ajustes entero, from_page=1), a settings.password_test, que
// contesta con cada regla (ok: true / false / null = sin comprobar) y lo pinta como lista. No guarda nada, y no es un
// <form> ni un type="password" para que el navegador no ofrezca guardar la contraseña.
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

  function icon(name) { return window.SW.icon(name, "icon-sm"); }

  function paint(data) {
    list.innerHTML = "";
    data.checks.forEach(function (c) {
      var li = document.createElement("li");
      li.className = c.ok === true ? "is-ok" : c.ok === false ? "is-bad" : "is-unknown";
      li.appendChild(icon(c.ok === true ? "check-circle" : c.ok === false ? "x" : "clock"));
      var text = document.createElement("span");
      text.textContent = c.label;
      li.appendChild(text);
      if (c.message) {
        var why = document.createElement("small");
        why.className = "muted";
        why.textContent = c.message;
        li.appendChild(why);
      }
      list.appendChild(li);
    });
    summary.textContent = data.summary;
    summary.className = "password-test-summary " + (data.ok ? "text-ok" : "text-danger");
    box.hidden = false;
  }

  function body() {
    var data = settingsForm ? new FormData(settingsForm) : new FormData();
    form.querySelectorAll("input[name]").forEach(function (input) { data.append(input.name, input.value); });
    if (settingsForm) data.append("from_page", "1");
    return data;
  }

  function run() {
    if (!password.value) { password.focus(); return; }
    button.disabled = true;
    window.SW.getJSON(form.dataset.action, { method: "POST", body: body() })
      .then(paint)
      .catch(function () {
        list.innerHTML = "";
        summary.textContent = t("Network error.");
        summary.className = "password-test-summary text-danger";
        box.hidden = false;
      })
      .finally(function () { button.disabled = false; });
  }

  button.addEventListener("click", run);
  form.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && event.target.tagName === "INPUT" && event.target.type === "text") {
      event.preventDefault();
      run();
    }
  });
})();
